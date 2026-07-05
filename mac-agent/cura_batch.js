/* cura_batch.js — PixInsight PJSR Batch-Skript (manuelle Vorverarbeitung)
 *
 * Wird headless vom Mac-Agent aufgerufen. Der Agent generiert einen Wrapper,
 * der die Konfiguration als globale JS-Variablen setzt und dieses Skript
 * inkludiert.
 *
 * Pipeline: ImageCalibration -> StarAlignment -> ImageIntegration
 * Alle Frames (Lights + Flats/Darks/Bias) liegen im Input-Verzeichnis
 * (vom Backend per SMB vom NAS geholt und ins ZIP gepackt).
 * Frame-Typ wird am Dateinamen-Präfix erkannt (Light_, Dark_, Flat_, Bias_).
 *
 * API-Referenz: grapeot/PixInsightMonoScript (funktionierendes PJSR-Skript)
 *   - ImageIntegration.images:  [true, path, "", ""]  (4 Elemente)
 *   - ImageCalibration.targetFrames: [true, path]      (2 Elemente)
 *   - StarAlignment.targets:    [true, true, path]    (3 Elemente)
 *   - ImageIntegration Ergebnis: ImageWindow.windowById(P.integrationImageId)
 *   - StarAlignment Ergebnis: P.outputData[c][0]
 *   - searchDirectory(dir + '/*.fit') statt FileFind
 */

// ─── Parameter (globale Variablen vom Wrapper) ───
var inputDir = "";
var outputDir = "";
var mode = "fastbatch";
var frameInfo = {};
// Calib aus dem Agent-Cache: { masterBias, masterDark, masterFlat (Pfad
// oder ""), biasSubs, darkSubs, flatSubs (Pfad-Arrays) }. Leer = Legacy-
// Modus (Calib liegt mit im Input-Verzeichnis).
var calib = {};

if (typeof CURA_INPUT_DIR !== "undefined") {
    inputDir  = CURA_INPUT_DIR;
    outputDir = CURA_OUTPUT_DIR;
    mode      = CURA_MODE;
    frameInfo = CURA_FRAME_INFO;
}
if (typeof CURA_CALIB !== "undefined" && CURA_CALIB) {
    calib = CURA_CALIB;
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

// ─── Datei-Logging ───
// PixInsight schreibt die Script-Console auf macOS in die GUI-Konsole, NICHT
// nach stdout. Damit der Mac-Agent (und wir) sehen, was das Skript tut bzw.
// woran es scheitert, schreiben wir zusätzlich in eine Logdatei im Output.
var CURA_LOG = outputDir + "/cura_batch.log";
var CURA_LOGBUF = "";
function flog(msg) {
    console.writeln(msg);
    CURA_LOGBUF += msg + "\n";
}
function flush() {
    try { File.writeTextFile(CURA_LOG, CURA_LOGBUF); } catch (e) { /* ignore */ }
}
flog("=== cura-stro Batch (Script gestartet) ===");
flog("Input:  " + inputDir);
flog("Output: " + outputDir);
flog("Mode:   " + mode);
flush();

// ─── Hilfsfunktionen ───

function findImageFiles(dir) {
    // searchDirectory ist eine PJSR-Globalfunktion (glob-like)
    var files = [];
    var exts = ["*.fit", "*.fits", "*.fts", "*.xisf", "*.tif", "*.tiff"];
    for (var e = 0; e < exts.length; e++) {
        try {
            var found = searchDirectory(dir + "/" + exts[e]);
            if (found) {
                for (var i = 0; i < found.length; i++) {
                    files.push(found[i]);
                }
            }
        } catch (ex) {
            // searchDirectory wirft bei leerem Verzeichnis — ignorieren
        }
    }
    return files;
}

function findImageFilesRecursive(dir) {
    var files = findImageFiles(dir);
    // Auch Unterordner durchsuchen (ASIAir legt manchmal in Subdirs ab)
    if (!File.directoryExists(dir)) return files;
    try {
        var entries = searchDirectory(dir + "/*");
        if (entries) {
            for (var i = 0; i < entries.length; i++) {
                if (File.directoryExists(entries[i])) {
                    var sub = findImageFilesRecursive(entries[i]);
                    for (var j = 0; j < sub.length; j++) {
                        files.push(sub[j]);
                    }
                }
            }
        }
    } catch (ex) {
        // ignore
    }
    return files;
}

function classifyFrame(filepath) {
    // Dateinamen aus Pfad extrahieren
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

// ─── Ab hier: alles in try/catch, damit Fehler im Datei-Log landen ───
try {

function filterOf(filepath) {
    // Filter aus dem ASIAir-Dateinamen extrahieren:
    //   Light_NGC 1499_300.0s_Bin1_OIII_20241225-210058_0010.fit
    // → Token nach "BinN". Funktioniert auch für _c/_r-Postfixe, da diese
    // nur hinten angehängt werden. Fallback: "NoFilter" (z. B. Farbkamera).
    var name = filepath;
    var slash = name.lastIndexOf('/');
    if (slash >= 0) name = name.substring(slash + 1);
    var dot = name.lastIndexOf('.');
    if (dot >= 0) name = name.substring(0, dot);
    var parts = name.split('_');
    for (var i = 0; i < parts.length - 1; i++) {
        if (/^bin\d+$/i.test(parts[i])) {
            var f = parts[i + 1].replace(/[^A-Za-z0-9+-]/g, "");
            if (f.length > 0 && !/^\d{8}/.test(f)) return f;
        }
    }
    return "NoFilter";
}

// ─── Alle Dateien sammeln ───
var allFiles = findImageFilesRecursive(inputDir);

flog("searchDirectory fand " + allFiles.length + " Bilddatei(en) unter " + inputDir);
for (var _f = 0; _f < allFiles.length; ++_f) {
    flog("  [" + _f + "] " + allFiles[_f]);
}
flush();

var lights = [], darks = [], flats = [], biases = [], darkflats = [];

for (var i = 0; i < allFiles.length; ++i) {
    var type = classifyFrame(allFiles[i]);
    if (type === "light")          lights.push(allFiles[i]);
    else if (type === "dark")      darks.push(allFiles[i]);
    else if (type === "flat")      flats.push(allFiles[i]);
    else if (type === "bias")     biases.push(allFiles[i]);
    else if (type === "darkflat") darkflats.push(allFiles[i]);
    else                           lights.push(allFiles[i]);
}

flog("Gefunden: " + lights.length + " Lights, " +
    darks.length + " Darks, " + flats.length + " Flats, " +
    biases.length + " Bias, " + darkflats.length + " DarkFlats");
flush();

if (lights.length === 0) {
    flog("KRITISCH: Keine Light-Frames gefunden — Abbruch");
    flush();
    throw new Error("No light frames");
}

// ─── Verzeichnisse ───
var calDir = outputDir + "/calibrated";
var alignedDir = outputDir + "/aligned";
if (!File.directoryExists(calDir))
    File.createDirectory(calDir, true);
if (!File.directoryExists(alignedDir))
    File.createDirectory(alignedDir, true);

// ─── Hilfsfunktion: Bild speichern ───
function saveImage(filePath, imageWindow) {
    var F = new FileFormat(".xisf", false, true);
    if (F.isNull)
        throw new Error("No installed file format can write .xisf files.");
    var f = new FileFormatInstance(F);
    if (f.isNull)
        throw new Error("Unable to instantiate file format: " + F.name);
    var outputHints = "properties fits-keywords no-compress-data block-alignment 4096 max-inline-block-size 3072 no-embedded-data no-resolution up-bottom";
    if (!f.create(filePath, outputHints))
        throw new Error("Error creating output file: " + filePath);
    var d = new ImageDescription;
    d.bitsPerSample = 32;
    d.ieeefpSampleFormat = true;
    if (!f.setOptions(d))
        throw new Error("Unable to set output file options: " + filePath);
    if (F.canStoreImageProperties)
        if (F.supportsViewProperties)
            imageWindow.mainView.exportProperties(f);
    if (F.canStoreKeywords)
        f.keywords = imageWindow.keywords;
    if (!f.writeImage(imageWindow.mainView.image))
        throw new Error("Error writing output file: " + filePath);
    f.close();
    console.writeln("  Gespeichert: " + filePath);
    return filePath;
}

// ─── 1. Master-Frames erstellen (Bias/Dark/Flat) ───
var masterBias = null, masterDark = null, masterFlat = null;

function buildMaster(frames, label, outPath, normalize) {
    if (frames.length === 0) return null;
    console.writeln("Erstelle " + label + "-Master aus " + frames.length + " Frames...");

    var images = [];
    for (var i = 0; i < frames.length; ++i) {
        // Format: [enabled, path, drizzlePath, localNormDataPath]
        images.push([true, frames[i], "", ""]);
    }

    var P = new ImageIntegration;
    P.images = images;
    P.inputHints = "fits-keywords normalize raw cfa signed-is-physical";
    P.combination = ImageIntegration.prototype.Average;
    // Master-Frames werden nicht gewichtet (wie WBPP): DontCare.
    // ("Average" ist ein combination-Enum, kein weightMode-Wert.)
    if (typeof ImageIntegration.prototype.DontCare !== "undefined")
        P.weightMode = ImageIntegration.prototype.DontCare;
    P.weightKeyword = "";
    P.weightScale = ImageIntegration.prototype.WeightScale_BWMV;
    P.normalization = normalize
        ? ImageIntegration.prototype.AdditiveWithScaling
        : ImageIntegration.prototype.NoNormalization;
    P.rejection = ImageIntegration.prototype.LinearFit;
    P.rejectionNormalization = ImageIntegration.prototype.Scale;
    P.linearFitLow = 5.0;
    P.linearFitHigh = 4.0;
    P.clipLow = true;
    P.clipHigh = true;
    P.rangeClipLow = true;
    P.rangeLow = 0.0;
    P.rangeClipHigh = false;
    P.rangeHigh = 0.98;
    P.generate64BitResult = false;
    P.generateRejectionMaps = false;
    P.generateIntegratedImage = true;
    P.generateDrizzleData = false;
    P.closePreviousImages = false;
    P.noGUIMessages = true;
    P.showImages = false;
    P.useFileThreads = true;
    P.useBufferThreads = true;
    P.maxBufferThreads = 8;

    var ok = P.executeGlobal();
    processEvents();
    gc();

    if (!ok) {
        console.warningln("  WARNUNG: " + label + "-Integration fehlgeschlagen");
        return null;
    }

    // Ergebnis-Window über integrationImageId finden
    var win = ImageWindow.windowById(P.integrationImageId);
    if (win.isNull) {
        console.warningln("  WARNUNG: Kein Ergebnis-Window fuer " + label);
        return null;
    }

    try {
        saveImage(outPath, win);
    } finally {
        win.forceClose();
    }

    console.writeln("  " + label + "-Master gespeichert: " + outPath);
    return outPath;
}

// Calib-Quellen (Priorität): 1) fertiger Master aus dem Agent-Cache,
// 2) Roh-Subs aus dem Agent-Cache, 3) Legacy: Frames im Input-Verzeichnis.
// Neu gebaute Master landen in calDir → Ergebnis-ZIP → das Backend legt
// sie aufs NAS (Calib/Masters/) und schickt beim nächsten Mal nur noch sie.
var biasSubs = (calib.biasSubs && calib.biasSubs.length) ? calib.biasSubs : biases;
var darkSubs = (calib.darkSubs && calib.darkSubs.length) ? calib.darkSubs : darks;
var flatSubs = (calib.flatSubs && calib.flatSubs.length) ? calib.flatSubs : flats;

if (calib.masterBias) {
    masterBias = calib.masterBias;
    flog("Bias-Master aus Cache: " + masterBias);
} else {
    masterBias = buildMaster(biasSubs, "Bias", calDir + "/master_bias.xisf", false);
}
if (calib.masterDark) {
    masterDark = calib.masterDark;
    flog("Dark-Master aus Cache: " + masterDark);
} else {
    masterDark = buildMaster(darkSubs, "Dark", calDir + "/master_dark.xisf", false);
}
if (calib.masterFlat) {
    masterFlat = calib.masterFlat;
    flog("Flat-Master aus Cache: " + masterFlat);
} else {
    masterFlat = buildMaster(flatSubs, "Flat", calDir + "/master_flat.xisf", true);
}
flush();

// ─── 2. ImageCalibration ───
flog("\n--- ImageCalibration ---");
flush();

var calibratedLights = [];

if (masterBias == null && masterDark == null && masterFlat == null) {
    // ImageCalibration braucht mindestens ein aktiviertes Master-Frame,
    // sonst schlägt executeGlobal fehl. Ohne Calib-Frames: Lights direkt
    // zum Alignment durchreichen.
    flog("Keine Kalibrier-Frames (Bias/Dark/Flat) — Kalibrierung uebersprungen");
    flush();
    calibratedLights = lights;
} else {

var icInputs = [];
for (var i = 0; i < lights.length; ++i) {
    // Format: [enabled, path]
    icInputs.push([true, lights[i]]);
}

var ic = new ImageCalibration;
ic.targetFrames = icInputs;
ic.enableCFA = false;
ic.cfaPattern = ImageCalibration.prototype.Auto;
ic.inputHints = "fits-keywords normalize raw cfa signed-is-physical";
ic.outputHints = "properties fits-keywords no-compress-data no-embedded-data no-resolution";
ic.pedestal = 0;
ic.pedestalMode = ImageCalibration.prototype.Keyword;
ic.pedestalKeyword = "";
ic.overscanEnabled = false;
ic.masterBiasEnabled = masterBias != null;
ic.masterBiasPath = masterBias || "";
ic.masterDarkEnabled = masterDark != null;
ic.masterDarkPath = masterDark || "";
ic.masterFlatEnabled = masterFlat != null;
ic.masterFlatPath = masterFlat || "";
ic.calibrateBias = false;
ic.calibrateDark = true;
ic.calibrateFlat = true;
ic.optimizeDarks = true;
ic.darkOptimizationThreshold = 0.000;
ic.evaluateNoise = true;
// PI 1.8.9: gueltige Enum-Namen sind NoiseEvaluation_MRS / NoiseEvaluation_KSigma.
// ("Iterative" existiert nicht -> undefined -> "invalid argument type"-Crash.)
if (typeof ImageCalibration.prototype.NoiseEvaluation_MRS !== "undefined")
    ic.noiseEvaluationAlgorithm = ImageCalibration.prototype.NoiseEvaluation_MRS;
ic.outputDirectory = calDir;
ic.outputExtension = ".xisf";
ic.outputPostfix = "_c";
ic.outputPrefix = "";
ic.overwriteExistingFiles = true;
ic.onError = ImageCalibration.prototype.Continue;
ic.noGUIMessages = true;
ic.showImages = false;
ic.useFileThreads = true;
ic.fileThreadOverload = 1.00;
ic.maxBufferThreads = 8;

var icOk = ic.executeGlobal();
processEvents();
gc();

if (!icOk) {
    console.criticalln("ImageCalibration fehlgeschlagen — Abbruch");
    throw new Error("ImageCalibration failed");
}

// Kalibrierte Lights über outputData finden
if (ic.outputData) {
    for (var c = 0; c < ic.outputData.length; ++c) {
        var filePath = ic.outputData[c][0]; // outputData.outputImage
        if (filePath && filePath != "" && File.exists(filePath)) {
            calibratedLights.push(filePath);
        }
    }
}
// Fallback: Verzeichnis scannen
if (calibratedLights.length === 0) {
    calibratedLights = findImageFiles(calDir);
}
flog("Kalibriert: " + calibratedLights.length + " Frames");
flush();

} // else (Kalibrierung mit Master-Frames)

if (calibratedLights.length === 0) {
    console.criticalln("ImageCalibration lieferte keine Ergebnisse — Abbruch");
    throw new Error("ImageCalibration produced no output");
}

// ─── 3. StarAlignment ───
flog("\n--- StarAlignment ---");
flush();

var saInputs = [];
for (var i = 0; i < calibratedLights.length; ++i) {
    // Format: [enabled, isFile, path]
    saInputs.push([true, true, calibratedLights[i]]);
}

var sa = new StarAlignment;
sa.structureLayers = 5;
sa.noiseLayers = 0;
sa.hotPixelFilterRadius = 1;
sa.noiseReductionFilterRadius = 0;
sa.sensitivity = 0.10;
sa.peakResponse = 0.80;
sa.maxStarDistortion = 0.50;
sa.upperLimit = 1.00;
sa.invert = false;
sa.distortionModel = "";
sa.undistortedReference = false;
sa.distortionCorrection = false;
sa.distortionMaxIterations = 20;
sa.distortionTolerance = 0.005;
sa.distortionAmplitude = 2;
sa.localDistortion = true;
sa.localDistortionScale = 256;
sa.localDistortionTolerance = 0.050;
sa.localDistortionRejection = 2.50;
sa.localDistortionRejectionWindow = 64;
sa.localDistortionRegularization = 0.010;
sa.matcherTolerance = 0.0500;
sa.ransacTolerance = 2.00;
sa.ransacMaxIterations = 2000;
sa.ransacMaximizeInliers = 1.00;
sa.ransacMaximizeOverlapping = 1.00;
sa.ransacMaximizeRegularity = 1.00;
sa.ransacMinimizeError = 1.00;
sa.maxStars = 0;
sa.fitPSF = StarAlignment.prototype.FitPSF_DistortionOnly;
sa.psfTolerance = 0.50;
sa.useTriangles = false;
sa.polygonSides = 5;
sa.descriptorsPerStar = 20;
sa.restrictToPreviews = true;
sa.intersection = StarAlignment.prototype.MosaicOnly;
sa.useBrightnessRelations = false;
sa.useScaleDifferences = false;
sa.scaleTolerance = 0.100;
sa.referenceImage = calibratedLights[0];
sa.referenceIsFile = true;
sa.targets = saInputs;
sa.inputHints = "";
sa.outputHints = "";
sa.mode = StarAlignment.prototype.RegisterMatch;
sa.writeKeywords = true;
sa.generateMasks = false;
sa.generateDrizzleData = false;
sa.generateDistortionMaps = false;
sa.frameAdaptation = false;
sa.randomizeMosaic = false;
sa.noGUIMessages = true;
sa.useSurfaceSplines = false;
sa.extrapolateLocalDistortion = true;
sa.splineSmoothness = 0.050;
sa.pixelInterpolation = StarAlignment.prototype.Auto;
sa.clampingThreshold = 0.30;
sa.outputDirectory = alignedDir;
sa.outputExtension = ".xisf";
sa.outputPrefix = "";
sa.outputPostfix = "_r";
sa.maskPostfix = "_m";
sa.distortionMapPostfix = "_dm";
sa.outputSampleFormat = StarAlignment.prototype.SameAsTarget;
sa.overwriteExistingFiles = true;
sa.onError = StarAlignment.prototype.Continue;
sa.useFileThreads = true;
sa.fileThreadOverload = 1.20;
sa.maxFileReadThreads = 8;
sa.maxFileWriteThreads = 8;

var saOk = sa.executeGlobal();
processEvents();
gc();

if (!saOk) {
    console.criticalln("StarAlignment fehlgeschlagen — Abbruch");
    throw new Error("StarAlignment failed");
}

// Ausgerichtete Lights über outputData finden
var alignedLights = [];
if (sa.outputData) {
    for (var c = 0; c < sa.outputData.length; ++c) {
        var filePath = sa.outputData[c][0]; // outputData.outputImage
        if (filePath && filePath != "" && File.exists(filePath)) {
            alignedLights.push(filePath);
        }
    }
}
// Fallback: Verzeichnis scannen
if (alignedLights.length === 0) {
    alignedLights = findImageFiles(alignedDir);
}
flog("Ausgerichtet: " + alignedLights.length + " Frames");
flush();

if (alignedLights.length === 0) {
    console.criticalln("StarAlignment lieferte keine Ergebnisse — Abbruch");
    throw new Error("StarAlignment produced no output");
}

// ─── 4. ImageIntegration (Stack) — getrennt je Filter ───
// Alle Frames wurden gemeinsam auf EINE Referenz ausgerichtet; die
// Filter-Master sind dadurch zueinander registriert und können später
// direkt kombiniert werden (z. B. SHO).
flog("\n--- ImageIntegration (je Filter) ---");
flush();

var objName = "result";
if (frameInfo && frameInfo.object_name) {
    objName = frameInfo.object_name;
}

// Ausgerichtete Frames nach Filter gruppieren
var filterGroups = {};
for (var i = 0; i < alignedLights.length; ++i) {
    var flt = filterOf(alignedLights[i]);
    if (!filterGroups[flt]) filterGroups[flt] = [];
    filterGroups[flt].push(alignedLights[i]);
}
var filterNames = [];
for (var flt in filterGroups) filterNames.push(flt);
filterNames.sort();

flog("Filter-Gruppen: " + filterNames.length);
for (var g = 0; g < filterNames.length; ++g) {
    flog("  " + filterNames[g] + ": " + filterGroups[filterNames[g]].length + " Frames");
}
flush();

function integrateGroup(frames, outPath, label) {

flog("\nIntegriere " + label + " (" + frames.length + " Frames) → " + outPath);
flush();

var iiInputs = [];
for (var i = 0; i < frames.length; ++i) {
    // Format: [enabled, path, drizzlePath, localNormDataPath]
    iiInputs.push([true, frames[i], "", ""]);
}

var ii = new ImageIntegration;
ii.images = iiInputs;
ii.inputHints = "fits-keywords normalize raw cfa signed-is-physical";
ii.combination = ImageIntegration.prototype.Average;
// Enum-Name je nach PI-Version: NoiseEvaluation (aelter) / PSFSignalWeight (1.8.9+).
if (typeof ImageIntegration.prototype.PSFSignalWeight !== "undefined")
    ii.weightMode = ImageIntegration.prototype.PSFSignalWeight;
else if (typeof ImageIntegration.prototype.NoiseEvaluation !== "undefined")
    ii.weightMode = ImageIntegration.prototype.NoiseEvaluation;
ii.weightKeyword = "";
ii.weightScale = ImageIntegration.prototype.WeightScale_BWMV;
ii.adaptiveGridSize = 16;
ii.adaptiveNoScale = false;
ii.ignoreNoiseKeywords = false;
ii.normalization = ImageIntegration.prototype.AdditiveWithScaling;
ii.rejection = ImageIntegration.prototype.WinsorizedSigmaClip;
ii.rejectionNormalization = ImageIntegration.prototype.Scale;
ii.minMaxLow = 1;
ii.minMaxHigh = 1;
ii.pcClipLow = 0.200;
ii.pcClipHigh = 0.100;
ii.sigmaLow = 4.000;
ii.sigmaHigh = 3.000;
ii.winsorizationCutoff = 5.000;
ii.linearFitLow = 5.000;
ii.linearFitHigh = 4.000;
ii.esdOutliersFraction = 0.30;
ii.esdAlpha = 0.05;
ii.esdLowRelaxation = 1.50;
ii.ccdGain = 1.00;
ii.ccdReadNoise = 10.00;
ii.ccdScaleNoise = 0.00;
ii.clipLow = true;
ii.clipHigh = true;
ii.rangeClipLow = true;
ii.rangeLow = 0.0;
ii.rangeClipHigh = false;
ii.rangeHigh = 0.98;
ii.mapRangeRejection = true;
ii.reportRangeRejection = false;
ii.largeScaleClipLow = false;
ii.largeScaleClipLowProtectedLayers = 2;
ii.largeScaleClipLowGrowth = 2;
ii.largeScaleClipHigh = false;
ii.largeScaleClipHighProtectedLayers = 2;
ii.largeScaleClipHighGrowth = 2;
ii.generate64BitResult = false;
ii.generateRejectionMaps = false;
ii.generateIntegratedImage = true;
ii.generateDrizzleData = false;
ii.closePreviousImages = false;
ii.bufferSizeMB = 16;
ii.stackSizeMB = 1024;
ii.autoMemorySize = true;
ii.autoMemoryLimit = 0.75;
ii.useROI = false;
ii.roiX0 = 0;
ii.roiY0 = 0;
ii.roiX1 = 0;
ii.roiY1 = 0;
ii.useCache = true;
ii.evaluateNoise = true;
ii.mrsMinDataFraction = 0.010;
ii.subtractPedestals = false;
ii.truncateOnOutOfRange = false;
ii.noGUIMessages = true;
ii.showImages = false;
ii.useFileThreads = true;
ii.fileThreadOverload = 1.00;
ii.useBufferThreads = true;
ii.maxBufferThreads = 8;

var iiOk = ii.executeGlobal();
processEvents();
gc();

if (!iiOk) {
    flog("KRITISCH: ImageIntegration fehlgeschlagen (" + label + ")");
    flush();
    throw new Error("ImageIntegration failed: " + label);
}

// Ergebnis-Window über integrationImageId finden
var intWin = ImageWindow.windowById(ii.integrationImageId);
if (intWin.isNull) {
    flog("KRITISCH: ImageIntegration lieferte kein Ergebnis-Window (" + label + ")");
    flush();
    throw new Error("ImageIntegration produced no window: " + label);
}

try {
    saveImage(outPath, intWin);
} finally {
    intWin.forceClose();
}

flog("Master (" + label + ") gespeichert: " + outPath);
flush();
return outPath;

} // integrateGroup

// ImageIntegration braucht mindestens 3 Frames pro Stack.
var masters = [];
var skipped = [];
for (var g = 0; g < filterNames.length; ++g) {
    var flt = filterNames[g];
    var frames = filterGroups[flt];
    if (frames.length < 3) {
        flog("WARNUNG: Filter " + flt + " hat nur " + frames.length +
             " Frame(s) — Integration braucht min. 3, wird übersprungen");
        flush();
        skipped.push(flt);
        continue;
    }
    var suffix = (filterNames.length === 1 && flt === "NoFilter") ? "" : "_" + flt;
    var outPath = outputDir + "/master_" + objName + suffix + ".xisf";
    masters.push(integrateGroup(frames, outPath, flt));
}

if (masters.length === 0) {
    flog("KRITISCH: Keine Filter-Gruppe hatte genug Frames für einen Stack");
    flush();
    throw new Error("No filter group had enough frames to integrate");
}

flog("\n=== Batch abgeschlossen ===");
flog("Output-Verzeichnis: " + outputDir);
flog("Master (" + masters.length + "):");
for (var m = 0; m < masters.length; ++m) {
    flog("  " + masters[m]);
}
if (skipped.length > 0) {
    flog("Übersprungen (zu wenige Frames): " + skipped.join(", "));
}
flush();

} catch (cura_err) {
    // Jeder Fehler landet hier UND im Datei-Log — sonst nur unsichtbar in der
    // PixInsight-GUI-Konsole.
    flog("\n!!! FATAL: " + cura_err);
    if (cura_err && cura_err.stack) flog(cura_err.stack);
    flush();
    try {
        File.writeTextFile(outputDir + "/cura_batch_error.log",
            String(cura_err) + "\n" + (cura_err && cura_err.stack ? cura_err.stack : ""));
    } catch (e2) { /* ignore */ }
    throw cura_err;   // Exit-Code != 0 für den Agent erzwingen
}
