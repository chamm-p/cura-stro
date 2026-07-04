/* cura_batch.js — PixInsight PJSR Batch-Skript (manuelle Vorverarbeitung)
 *
 * Wird headless vom Mac-Agent aufgerufen. Da PixInsight keine beliebigen
 * CLI-Argumente an Skripte weiterreicht, übergibt der Agent die Parameter
 * über eine JSON-Config-Datei. Der Wrapper setzt die globale Variable
 * CURA_CONFIG_PATH, dieses Skript liest sie aus.
 *
 * Pipeline: ImageCalibration → StarAlignment → ImageIntegration
 * Alle Frames (Lights + Flats/Darks/Bias) liegen im Input-Verzeichnis
 * (vom Backend per SMB vom NAS geholt und ins ZIP gepackt).
 * Frame-Typ wird am Dateinamen-Präfix erkannt (Light_, Dark_, Flat_, Bias_).
 *
 * PJSR-API basiert auf Referenz-Implementierungen (astro-pipeline von
 * ClemDeepSky). Die korrekte Array-Form für targetFrames/images ist:
 *   ImageCalibration.targetFrames = [[true, path], ...]
 *   StarAlignment.targets         = [[true, true, path], ...]
 *   ImageIntegration.images       = [[true, true, path, ""], ...]
 * Properties nutzen Enum-Konstanten (Prototype-Werte), keine Strings.
 */

#feature-id    cura-stro/batch
#feature-label cura-stro Batch-Vorverarbeitung

#include <pjsr/DataType.jsh>

// ─── Parameter laden (Config-Datei oder argv) ───
var inputDir = "";
var outputDir = "";
var infoFile = "";
var mode = "wbpp";

if (typeof CURA_CONFIG_PATH !== "undefined" && CURA_CONFIG_PATH && !CURA_CONFIG_PATH.isEmpty()) {
    console.writeln("Lade Konfiguration aus: " + CURA_CONFIG_PATH);
    try {
        var configText = File.readTextFile(CURA_CONFIG_PATH);
        var config = JSON.parse(configText);
        inputDir  = config.inputDir  || "";
        outputDir = config.outputDir || "";
        infoFile  = config.infoFile  || "";
        mode      = config.mode      || "wbpp";
    } catch (e) {
        console.criticalln("Fehler beim Lesen der Config-Datei: " + e);
        throw e;
    }
} else {
    console.writeln("Keine Config-Datei — parse argv");
    for (var i = 0; i < argc; ++i) {
        var arg = argv[i];
        if (arg.startsWith("--input="))
            inputDir = arg.substring(8);
        else if (arg.startsWith("--output="))
            outputDir = arg.substring(9);
        else if (arg.startsWith("--info="))
            infoFile = arg.substring(7);
        else if (arg.startsWith("--mode="))
            mode = arg.substring(7);
    }
}

if (inputDir.isEmpty() || outputDir.isEmpty()) {
    console.criticalln("cura_batch: --input und --output erforderlich");
    throw new Error("Missing arguments");
}

console.writeln("=== cura-stro Batch ===");
console.writeln("Input:  " + inputDir);
console.writeln("Output: " + outputDir);
console.writeln("Mode:   " + mode);

// ─── Frame-Info laden (optional) ───
var frameInfo = {};
if (!infoFile.isEmpty() && File.exists(infoFile)) {
    try {
        frameInfo = JSON.parse(File.readTextFile(infoFile));
        console.writeln("Frame-Info: " + JSON.stringify(frameInfo));
    } catch (e) {
        console.warningln("Konnte Frame-Info nicht laden: " + e);
    }
}

// ─── Output-Verzeichnis sicherstellen ───
if (!File.directoryExists(outputDir)) {
    File.createDirectory(outputDir, true);
}

// ─── Hilfsfunktionen ───
function listFiles(dir) {
    var files = [];
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
    var ff = new FileFind;
    ff.begin(dir + "/*");
    while (ff.next()) {
        if (ff.isDirectory) {
            if (ff.name !== "." && ff.name !== "..") {
                files = files.concat(listFilesRecursive(dir + "/" + ff.name));
            }
        } else {
            files.push(dir + "/" + ff.name);
        }
    }
    ff.end();
    return files;
}

function classifyFrame(filename) {
    var base = File.extractName(filename);
    var lower = base.toLowerCase();
    if (lower.startsWith("darkflat"))
        return "darkflat";
    if (lower.startsWith("light"))
        return "light";
    if (lower.startsWith("dark"))
        return "dark";
    if (lower.startsWith("flat"))
        return "flat";
    if (lower.startsWith("bias"))
        return "bias";
    return "light";
}

function isImageFile(filename) {
    var ext = File.extractExtension(filename).toLowerCase();
    return ext === "fit" || ext === "fits" || ext === "fts" ||
           ext === "xisf" || ext === "tif" || ext === "tiff";
}

function basename(path) {
    return File.extractName(path) + "." + File.extractExtension(path);
}

// ─── Alle Dateien sammeln ───
var allFiles = listFilesRecursive(inputDir);

var lights = [], darks = [], flats = [], biases = [], darkflats = [];

for (var i = 0; i < allFiles.length; ++i) {
    if (!isImageFile(allFiles[i])) continue;
    var type = classifyFrame(allFiles[i]);
    switch (type) {
        case "light":     lights.push(allFiles[i]); break;
        case "dark":      darks.push(allFiles[i]); break;
        case "flat":      flats.push(allFiles[i]); break;
        case "bias":      biases.push(allFiles[i]); break;
        case "darkflat":  darkflats.push(darkflats[i]); break;
        default:          lights.push(allFiles[i]); break;
    }
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
    ImageWindow.windows.forEach(function(w) { idsBefore[w.mainView.id] = true; });

    ii.executeGlobal();
    processEvents();
    gc();

    // Neue Fenster finden
    var newWins = [];
    ImageWindow.windows.forEach(function(w) {
        if (!idsBefore[w.mainView.id]) newWins.push(w);
    });

    if (newWins.length === 0) {
        console.warningln("  WARNUNG: Kein Ergebnis-Window für " + label);
        return null;
    }

    // Integration-Window ist das erste neue Fenster
    var intWin = newWins[0];
    var ok = intWin.saveAs(outPath, false, true, false, false);
    intWin.forceClose();

    // Alle verbleibenden neuen Fenster schließen
    newWins.forEach(function(w) {
        if (w.mainView.id !== intWin.mainView.id) w.forceClose();
    });

    if (ok) {
        console.writeln("  " + label + "-Master gespeichert: " + outPath);
        return outPath;
    } else {
        console.warningln("  WARNUNG: saveAs fehlgeschlagen für " + label);
        return null;
    }
}

masterBias = buildMaster(biases, "Bias", calDir + "/master_bias.xisf", false);
masterDark = buildMaster(darks, "Dark", calDir + "/master_dark.xisf", false);
masterFlat = buildMaster(flats, "Flat", calDir + "/master_flat.xisf", true);

// ─── 2. ImageCalibration ───
console.writeln("\n--- ImageCalibration ---");

var ic = new ImageCalibration();
ic.targetFrames = lights.map(function(f) { return [true, f]; });
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

// ─── 4. ImageIntegration ───
console.writeln("\n--- ImageIntegration ---");

var masterName = "master_" +
    (frameInfo.object_name || "result") + "_" +
    (frameInfo.filter_name || "L") + ".xisf";
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
ImageWindow.windows.forEach(function(w) { idsBeforeII[w.mainView.id] = true; });

ii.executeGlobal();
processEvents();
gc();

// Neue Fenster finden
var newWinsII = [];
ImageWindow.windows.forEach(function(w) {
    if (!idsBeforeII[w.mainView.id]) newWinsII.push(w);
});

if (newWinsII.length === 0) {
    console.criticalln("ImageIntegration lieferte kein Ergebnis-Window");
    throw new Error("ImageIntegration failed");
}

// Integration-Window ist das erste neue Fenster
var intWin = newWinsII[0];
var okSave = intWin.saveAs(masterPath, false, true, false, false);
intWin.forceClose();

// Alle verbleibenden neuen Fenster schließen
newWinsII.forEach(function(w) {
    if (w.mainView.id !== intWin.mainView.id) w.forceClose();
});

if (okSave) {
    console.writeln("Master gespeichert: " + masterPath);
} else {
    console.criticalln("saveAs fehlgeschlagen für Master");
    throw new Error("saveAs failed");
}

// ─── Abschluss ───
console.writeln("\n=== Batch abgeschlossen ===");
console.writeln("Output-Verzeichnis: " + outputDir);
console.writeln("Master: " + masterPath);
console.writeln("Ergebnisse können nun in PixInsight manuell weiterentwickelt werden.");
