/* cura_batch.js — PixInsight PJSR Batch-Skript (manuelle Vorverarbeitung)
 *
 * Wird headless vom Mac-Agent aufgerufen. Der Agent generiert einen Wrapper,
 * der die Konfiguration als globale JS-Variablen setzt und dieses Skript
 * inkludiert.  Kein JSON.parse / JSON.stringify — PJSR hat kein JSON-Objekt.
 *
 * Pipeline: ImageCalibration -> StarAlignment -> ImageIntegration
 * Alle Frames (Lights + Flats/Darks/Bias) liegen im Input-Verzeichnis
 * (vom Backend per SMB vom NAS geholt und ins ZIP gepackt).
 * Frame-Typ wird am Dateinamen-Präfix erkannt (Light_, Dark_, Flat_, Bias_).
 *
 * PJSR-Kompatibilität:
 *   - Kein JSON.parse / JSON.stringify  (kein JSON-Objekt in PJSR)
 *   - Kein String.startsWith()           (ES6, nicht in PJSR)
 *   - Kein Array.map / Array.forEach      (nicht zuverlässig in PJSR)
 *   - Kein #feature-id / #include         (nicht nötig für headless -r=)
 */

// ─── Parameter (globale Variablen vom Wrapper) ───
var inputDir = "";
var outputDir = "";
var mode = "fastbatch";
var frameInfo = {};

if (typeof CURA_INPUT_DIR !== "undefined") {
    inputDir  = CURA_INPUT_DIR;
    outputDir = CURA_OUTPUT_DIR;
    mode      = CURA_MODE;
    frameInfo = CURA_FRAME_INFO;
}

if (inputDir.length === 0 || outputDir.length === 0) {
    console.criticalln("cura_batch: inputDir und outputDir erforderlich");
    throw new Error("Missing arguments");
}

console.writeln("=== cura-stro Batch ===");
console.writeln("Input:  " + inputDir);
console.writeln("Output: " + outputDir);
console.writeln("Mode:   " + mode);

// ─── Output-Verzeichnis sicherstellen ───
if (!File.directoryExists(outputDir)) {
    File.createDirectory(outputDir, true);
}

// ─── Hilfsfunktionen (PJSR-kompatibel, keine ES6-Methoden) ───

function listFiles(dir) {
    var files = [];
    if (!File.directoryExists(dir)) return files;
    var ff = new FileFind;
    ff.begin(dir + "/*");
    while (ff.next()) {
        if (!ff.isDirectory) {
            files.push(dir + "/" + ff.name);
        }
    }
    ff.end();
    return files;
}

function listFilesRecursive(dir) {
    var files = [];
    if (!File.directoryExists(dir)) return files;
    var ff = new FileFind;
    ff.begin(dir + "/*");
    while (ff.next()) {
        if (ff.isDirectory) {
            if (ff.name !== "." && ff.name !== "..") {
                var sub = listFilesRecursive(dir + "/" + ff.name);
                for (var j = 0; j < sub.length; ++j) {
                    files.push(sub[j]);
                }
            }
        } else {
            files.push(dir + "/" + ff.name);
        }
    }
    ff.end();
    return files;
}

function classifyFrame(filepath) {
    // Dateinamen aus Pfad extrahieren (ohne PJSR-File.extractName-Abhängigkeit)
    var name = filepath;
    var slash = name.lastIndexOf('/');
    if (slash >= 0) name = name.substring(slash + 1);
    var lower = name.toLowerCase();
    if (lower.indexOf("darkflat") === 0) return "darkflat";
    if (lower.indexOf("light") === 0) return "light";
    if (lower.indexOf("dark") === 0) return "dark";
    if (lower.indexOf("flat") === 0) return "flat";
    if (lower.indexOf("bias") === 0) return "bias";
    return "light";
}

function isImageFile(filepath) {
    var ext = File.extractExtension(filepath).toLowerCase();
    return ext === "fit" || ext === "fits" || ext === "fts" ||
           ext === "xisf" || ext === "tif" || ext === "tiff";
}

// ─── Alle Dateien sammeln ───
var allFiles = listFilesRecursive(inputDir);

var lights = [], darks = [], flats = [], biases = [], darkflats = [];

for (var i = 0; i < allFiles.length; ++i) {
    if (!isImageFile(allFiles[i])) continue;
    var type = classifyFrame(allFiles[i]);
    if (type === "light")        lights.push(allFiles[i]);
    else if (type === "dark")    darks.push(allFiles[i]);
    else if (type === "flat")    flats.push(allFiles[i]);
    else if (type === "bias")    biases.push(allFiles[i]);
    else if (type === "darkflat") darkflats.push(allFiles[i]);
    else                          lights.push(allFiles[i]);
}

console.writeln("Gefunden: " + lights.length + " Lights, " +
    darks.length + " Darks, " + flats.length + " Flats, " +
    biases.length + " Bias, " + darkflats.length + " DarkFlats");

if (lights.length === 0) {
    console.criticalln("Keine Light-Frames gefunden — Abbruch");
    throw new Error("No light frames");
}

// ─── Verzeichnisse ───
var calDir = outputDir + "/calibrated";
var alignedDir = outputDir + "/aligned";
if (!File.directoryExists(calDir))
    File.createDirectory(calDir, true);
if (!File.directoryExists(alignedDir))
    File.createDirectory(alignedDir, true);

// ─── 1. Master-Frames erstellen (Bias/Dark/Flat) ───
var masterBias = null, masterDark = null, masterFlat = null;

function buildMaster(frames, label, outPath, normalize) {
    if (frames.length === 0) return null;
    console.writeln("Erstelle " + label + "-Master aus " + frames.length + " Frames...");

    var images = [];
    for (var i = 0; i < frames.length; ++i) {
        images.push([true, true, frames[i], ""]);
    }

    var ii = new ImageIntegration();
    ii.images = images;
    ii.combination = ImageIntegration.prototype.Average;
    ii.weightMode = ImageIntegration.prototype.Average;
    ii.normalization = normalize
        ? ImageIntegration.prototype.AdditiveWithScaling
        : ImageIntegration.prototype.NoNormalization;
    ii.rejection = ImageIntegration.prototype.LinearFit;
    ii.rejectionNormalization = ImageIntegration.prototype.Scale;
    ii.linearFitLow = 4.0;
    ii.linearFitHigh = 4.0;
    ii.clipLow = true;
    ii.clipHigh = true;
    ii.generateIntegratedImage = true;
    ii.generateRejectionMaps = false;

    // Snapshot der Fenster vor der Integration
    var idsBefore = {};
    var winsBefore = ImageWindow.windows;
    for (var i = 0; i < winsBefore.length; ++i) {
        idsBefore[winsBefore[i].mainView.id] = true;
    }

    ii.executeGlobal();
    processEvents();
    gc();

    // Neue Fenster finden
    var newWins = [];
    var winsAfter = ImageWindow.windows;
    for (var i = 0; i < winsAfter.length; ++i) {
        if (!idsBefore[winsAfter[i].mainView.id]) {
            newWins.push(winsAfter[i]);
        }
    }

    if (newWins.length === 0) {
        console.warningln("  WARNUNG: Kein Ergebnis-Window fuer " + label);
        return null;
    }

    var intWin = newWins[0];
    var ok = intWin.saveAs(outPath, false, true, false, false);
    intWin.forceClose();

    // Alle verbleibenden neuen Fenster schliessen
    for (var i = 1; i < newWins.length; ++i) {
        newWins[i].forceClose();
    }

    if (ok) {
        console.writeln("  " + label + "-Master gespeichert: " + outPath);
        return outPath;
    } else {
        console.warningln("  WARNUNG: saveAs fehlgeschlagen fuer " + label);
        return null;
    }
}

masterBias = buildMaster(biases, "Bias", calDir + "/master_bias.xisf", false);
masterDark = buildMaster(darks, "Dark", calDir + "/master_dark.xisf", false);
masterFlat = buildMaster(flats, "Flat", calDir + "/master_flat.xisf", true);

// ─── 2. ImageCalibration ───
console.writeln("\n--- ImageCalibration ---");

var ic = new ImageCalibration();
var icTargets = [];
for (var i = 0; i < lights.length; ++i) {
    icTargets.push([true, lights[i]]);
}
ic.targetFrames = icTargets;
ic.outputDirectory = calDir;
ic.outputExtension = ".xisf";
ic.outputPostfix = "_c";
ic.overwriteExistingFiles = true;
ic.onError = ImageCalibration.prototype.Continue;

if (masterBias) {
    ic.masterBiasEnabled = true;
    ic.masterBiasPath = masterBias;
} else {
    ic.masterBiasEnabled = false;
}

if (masterDark) {
    ic.masterDarkEnabled = true;
    ic.masterDarkPath = masterDark;
    ic.masterDarkOptimization = true;
} else {
    ic.masterDarkEnabled = false;
}

if (masterFlat) {
    ic.masterFlatEnabled = true;
    ic.masterFlatPath = masterFlat;
} else {
    ic.masterFlatEnabled = false;
}

ic.executeGlobal();
processEvents();
gc();

// Kalibrierte Lights finden
var calibratedLights = [];
var calFiles = listFiles(calDir);
for (var i = 0; i < calFiles.length; ++i) {
    if (isImageFile(calFiles[i])) {
        calibratedLights.push(calFiles[i]);
    }
}
console.writeln("Kalibriert: " + calibratedLights.length + " Frames");

if (calibratedLights.length === 0) {
    console.criticalln("ImageCalibration lieferte keine Ergebnisse — Abbruch");
    throw new Error("ImageCalibration failed");
}

// ─── 3. StarAlignment ───
console.writeln("\n--- StarAlignment ---");

var saTargets = [];
for (var i = 0; i < calibratedLights.length; ++i) {
    saTargets.push([true, true, calibratedLights[i]]);
}

var sa = new StarAlignment();
sa.referenceImage = calibratedLights[0];
sa.referenceIsFile = true;
sa.structureLayers = 5;
sa.noiseLayers = 0;
sa.hotPixelFilterRadius = 1;
sa.sensitivity = 0.50;
sa.peakResponse = 0.50;
sa.maxStarDistortion = 0.60;
sa.matcherTolerance = 0.0500;
sa.ransacTolerance = 2.0;
sa.maxStars = 0;
sa.intersection = StarAlignment.prototype.Always;
sa.generateDrizzleData = false;
sa.pixelInterpolation = StarAlignment.prototype.Auto;
sa.clampingThreshold = 0.30;
sa.outputPostfix = "_r";
sa.outputDirectory = alignedDir;
sa.outputExtension = ".xisf";
sa.overwriteExistingFiles = true;
sa.onError = StarAlignment.prototype.Continue;
sa.targets = saTargets;

sa.executeGlobal();
processEvents();
gc();

// Ausgerichtete Lights finden
var alignedLights = [];
var alignedFiles = listFiles(alignedDir);
for (var i = 0; i < alignedFiles.length; ++i) {
    if (isImageFile(alignedFiles[i])) {
        alignedLights.push(alignedFiles[i]);
    }
}
console.writeln("Ausgerichtet: " + alignedLights.length + " Frames");

if (alignedLights.length === 0) {
    console.criticalln("StarAlignment lieferte keine Ergebnisse — Abbruch");
    throw new Error("StarAlignment failed");
}

// ─── 4. ImageIntegration (Stack) ───
console.writeln("\n--- ImageIntegration ---");

var objName = frameInfo.object_name || "result";
var masterName = "master_" + objName + ".xisf";
var masterPath = outputDir + "/" + masterName;

var iiImages = [];
for (var i = 0; i < alignedLights.length; ++i) {
    iiImages.push([true, true, alignedLights[i], ""]);
}

var ii = new ImageIntegration();
ii.images = iiImages;
ii.combination = ImageIntegration.prototype.Average;
ii.weightMode = ImageIntegration.prototype.Average;
ii.normalization = ImageIntegration.prototype.AdditiveWithScaling;
ii.rejection = ImageIntegration.prototype.LinearFit;
ii.rejectionNormalization = ImageIntegration.prototype.Scale;
ii.linearFitLow = 4.0;
ii.linearFitHigh = 4.0;
ii.clipLow = true;
ii.clipHigh = true;
ii.generateIntegratedImage = true;
ii.generateRejectionMaps = false;

// Snapshot der Fenster vor der Integration
var idsBeforeII = {};
var winsBeforeII = ImageWindow.windows;
for (var i = 0; i < winsBeforeII.length; ++i) {
    idsBeforeII[winsBeforeII[i].mainView.id] = true;
}

ii.executeGlobal();
processEvents();
gc();

// Neue Fenster finden
var newWinsII = [];
var winsAfterII = ImageWindow.windows;
for (var i = 0; i < winsAfterII.length; ++i) {
    if (!idsBeforeII[winsAfterII[i].mainView.id]) {
        newWinsII.push(winsAfterII[i]);
    }
}

if (newWinsII.length === 0) {
    console.criticalln("ImageIntegration lieferte kein Ergebnis-Window");
    throw new Error("ImageIntegration failed");
}

var intWin = newWinsII[0];
var okSave = intWin.saveAs(masterPath, false, true, false, false);
intWin.forceClose();

for (var i = 1; i < newWinsII.length; ++i) {
    newWinsII[i].forceClose();
}

if (okSave) {
    console.writeln("Master gespeichert: " + masterPath);
} else {
    console.criticalln("saveAs fehlgeschlagen fuer Master");
    throw new Error("saveAs failed");
}

// ─── Abschluss ───
console.writeln("\n=== Batch abgeschlossen ===");
console.writeln("Output-Verzeichnis: " + outputDir);
console.writeln("Master: " + masterPath);
