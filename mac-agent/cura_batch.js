/* cura_batch.js — PixInsight PJSR Batch-Skript
 *
 * Wird headless vom Mac-Agent aufgerufen:
 *   PixInsight -run=cura_batch.js --input=<dir> --output=<dir> --info=<json>
 *
 * Führt die klassische Vorverarbeitung durch:
 *   1. Dateien nach Frame-Typ sortieren (ASIAir-Namenskonvention)
 *   2. ImageCalibration (Bias/Dark/Flat-Korrektur der Lights)
 *   3. StarAlignment (Registrierung)
 *   4. ImageIntegration (Stacking zum Master)
 *   5. Ergebnis ins Output-Verzeichnis schreiben
 *
 * Das Skript ist bewusst konservativ: es nutzt die Standard-Prozesse
 * von PixInsight ohne komplexe Parameter — für fortgeschrittene Optionen
 * (Drizzle, LocalNormalization, etc.) kann es erweitert werden.
 *
 * Alternativ kann hier auch das WBPP-Script (WeightedBatchPreProcessing)
 * aufgerufen werden, indem man den Pfad in BATCH_SCRIPT anpasst.
 */

#feature-id    cura-stro/batch
#feature-label cura-stro Batch-Vorverarbeitung (ImageCalibration → StarAlignment → ImageIntegration)

#include <pjsr/DataType.jsh>

// ─── Argumente parsen ───
var inputDir = "";
var outputDir = "";
var infoFile = "";

for (var i = 0; i < argc; ++i) {
    var arg = argv[i];
    if (arg.startsWith("--input="))
        inputDir = arg.substring(8);
    else if (arg.startsWith("--output="))
        outputDir = arg.substring(9);
    else if (arg.startsWith("--info="))
        infoFile = arg.substring(7);
}

if (inputDir.isEmpty() || outputDir.isEmpty()) {
    console.criticalln("cura_batch: --input und --output erforderlich");
    throw new Error("Missing arguments");
}

console.writeln("=== cura-stro Batch ===");
console.writeln("Input:  " + inputDir);
console.writeln("Output: " + outputDir);

// ─── Frame-Info laden (optional) ───
var frameInfo = {};
if (!infoFile.isEmpty() && File.exists(infoFile)) {
    try {
        var infoText = File.readTextFile(infoFile);
        frameInfo = JSON.parse(infoText);
        console.writeln("Frame-Info geladen: " + JSON.stringify(frameInfo));
    } catch (e) {
        console.warningln("Konnte Frame-Info nicht laden: " + e);
    }
}

// ─── Dateien nach Frame-Typ sortieren ───
// ASIAir-Namenskonvention:
//   Light_<obj>_<exp>s_Bin<n>[_<filter>]_<date>-<time>_<seq>.fit
//   Dark_<obj>_...
//   Flat_<obj>_...
//   Bias_<obj>_...

function listFiles(dir) {
    var files = [];
    var f = new File;
    if (!f.openForReading(dir)) {
        // Ist ein Verzeichnis — über SearchFile
        var search = new SearchFile;
        search.directory = dir;
        search.pattern = "*";
        search.matchMode = SearchFile.Mode递;
        search.recursive = false;
        search.execute();
        for (var i = 0; i < search.length; ++i) {
            if (!search.isDirectory(i)) {
                files.push(search.fullPath(i));
            }
        }
    }
    return files;
}

function classifyFrame(filename) {
    var base = File.extractName(filename);
    var lower = base.toLowerCase();
    if (lower.startsWith("light") || lower.startsWith("light_"))
        return "light";
    if (lower.startsWith("dark") || lower.startsWith("dark_"))
        return "dark";
    if (lower.startsWith("flat") || lower.startsWith("flat_"))
        return "flat";
    if (lower.startsWith("bias") || lower.startsWith("bias_"))
        return "bias";
    if (lower.startsWith("darkflat") || lower.startsWith("darkflat_"))
        return "darkflat";
    // Standard: als Light annehmen
    return "light";
}

function isImageFile(filename) {
    var ext = File.extractExtension(filename).toLowerCase();
    return ext === "fit" || ext === "fits" || ext === "fts" ||
           ext === "xisf" || ext === "tif" || ext === "tiff";
}

var allFiles = listFiles(inputDir);
var lights = [];
var darks = [];
var flats = [];
var biases = [];
var darkflats = [];

for (var i = 0; i < allFiles.length; ++i) {
    if (!isImageFile(allFiles[i])) continue;
    var type = classifyFrame(allFiles[i]);
    switch (type) {
        case "light":     lights.push(allFiles[i]); break;
        case "dark":      darks.push(allFiles[i]); break;
        case "flat":      flats.push(allFiles[i]); break;
        case "bias":      biases.push(allFiles[i]); break;
        case "darkflat":  darkflats.push(allFiles[i]); break;
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

// ─── Hilfsfunktion: Dateiname ohne Pfad ───
function basename(path) {
    return File.extractName(path) + "." + File.extractExtension(path);
}

// ─── 1. ImageCalibration ───
// Kalibriert die Lights mit Bias/Dark/Flat (falls vorhanden)
var calibratedLights = [];

if (biases.length > 0 || darks.length > 0 || flats.length > 0) {
    console.writeln("\n--- 1. ImageCalibration ---");

    var calDir = outputDir + "/calibrated";
    if (!File.directoryExists(calDir)) {
        File.createDirectory(calDir, true);
    }

    var ic = new ImageCalibration;
    ic.enableCFA = false;
    ic.overscanEnabled = false;

    // Bias-Frames
    if (biases.length > 0) {
        ic.masterBiasEnabled = true;
        // Ersten Bias als Master verwenden (oder alle mitteln)
        var biasMaster = biases[0];
        if (biases.length > 1) {
            // Mehrere Bias → mitteln
            var biasInt = new ImageIntegration;
            biasInt.images = biases.map(function(f) { return { path: f, enabled: true }; });
            biasInt.rejection = "NoRejection";
            biasInt.combination = "Average";
            biasInt.normalize = false;
            var biasOut = calDir + "/master_bias.xisf";
            biasInt.outputFile = biasOut;
            biasInt.executeGlobal();
            biasMaster = biasOut;
        }
        ic.masterBiasPath = biasMaster;
        console.writeln("Bias-Master: " + biasMaster);
    } else {
        ic.masterBiasEnabled = false;
    }

    // Dark-Frames
    if (darks.length > 0) {
        ic.masterDarkEnabled = true;
        var darkMaster = darks[0];
        if (darks.length > 1) {
            var darkInt = new ImageIntegration;
            darkInt.images = darks.map(function(f) { return { path: f, enabled: true }; });
            darkInt.rejection = "WinsorizedSigmaClip";
            darkInt.combination = "Average";
            darkInt.normalize = false;
            var darkOut = calDir + "/master_dark.xisf";
            darkInt.outputFile = darkOut;
            darkInt.executeGlobal();
            darkMaster = darkOut;
        }
        ic.masterDarkPath = darkMaster;
        ic.masterDarkOptimization = true;
        console.writeln("Dark-Master: " + darkMaster);
    } else {
        ic.masterDarkEnabled = false;
    }

    // Flat-Frames
    if (flats.length > 0) {
        ic.masterFlatEnabled = true;
        var flatMaster = flats[0];
        if (flats.length > 1) {
            var flatInt = new ImageIntegration;
            flatInt.images = flats.map(function(f) { return { path: f, enabled: true }; });
            flatInt.rejection = "WinsorizedSigmaClip";
            flatInt.combination = "Average";
            flatInt.normalize = true;
            var flatOut = calDir + "/master_flat.xisf";
            flatInt.outputFile = flatOut;
            flatInt.executeGlobal();
            flatMaster = flatOut;
        }
        ic.masterFlatPath = flatMaster;
        console.writeln("Flat-Master: " + flatMaster);
    } else {
        ic.masterFlatEnabled = false;
    }

    // Lights kalibrieren
    ic.targetFrames = lights.map(function(f) {
        return { enabled: true, path: f };
    });

    ic.outputDir = calDir;
    ic.outputExtension = ".xisf";
    ic.overwriteExistingFiles = true;
    ic.executeGlobal();

    // Kalibrierte Lights sammeln
    for (var i = 0; i < lights.length; ++i) {
        var calName = basename(lights[i]).replace(/\.(fit|fits|fts|xisf|tif|tiff)$/i, ".xisf");
        calibratedLights.push(calDir + "/" + calName);
    }
    console.writeln("Kalibriert: " + calibratedLights.length + " Frames");
} else {
    // Keine Kalibrierframes → Lights direkt verwenden
    console.writeln("\nKeine Kalibrierframes — überspringe ImageCalibration");
    calibratedLights = lights.slice();
}

// ─── 2. StarAlignment ───
console.writeln("\n--- 2. StarAlignment ---");
var alignedDir = outputDir + "/aligned";
if (!File.directoryExists(alignedDir)) {
    File.createDirectory(alignedDir, true);
}

var sa = new StarAlignment;
sa.referenceImage = calibratedLights[0];
sa.targetFrames = calibratedLights.map(function(f, i) {
    return { enabled: true, path: f };
});
sa.outputDir = alignedDir;
sa.outputExtension = ".xisf";
sa.overwriteExistingFiles = true;
sa.executeGlobal();

var alignedLights = calibratedLights.map(function(f) {
    var name = basename(f).replace(/\.(fit|fits|fts|xisf|tif|tiff)$/i, ".xisf");
    return alignedDir + "/" + name;
});

console.writeln("Ausgerichtet: " + alignedLights.length + " Frames");

// ─── 3. ImageIntegration ───
console.writeln("\n--- 3. ImageIntegration ---");
var masterPath = outputDir + "/master_" +
    (frameInfo.object_name || "result") + "_" +
    (frameInfo.filter_name || "L") + ".xisf";

var ii = new ImageIntegration;
ii.images = alignedLights.map(function(f) {
    return { enabled: true, path: f };
});
ii.rejection = "WinsorizedSigmaClip";
ii.combination = "Average";
ii.normalize = true;
ii.weighting = "SignalWeight";  // WBPP-ähnliche Gewichtung
ii.triggers = [0.1, 0.3];  // Sigma-Clip Thresholds
ii.outputFile = masterPath;
ii.executeGlobal();

console.writeln("\n=== Batch abgeschlossen ===");
console.writeln("Master: " + masterPath);
console.writeln("Output-Verzeichnis: " + outputDir);
