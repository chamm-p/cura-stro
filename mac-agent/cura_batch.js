/* cura_batch.js — PixInsight PJSR Batch-Skript (WBPP-Wrapper)
 *
 * Wird headless vom Mac-Agent aufgerufen. Da PixInsight keine beliebigen
 * CLI-Argumente an Skripte weiterreicht, übergibt der Agent die Parameter
 * über eine JSON-Config-Datei. Der Wrapper setzt die globale Variable
 * CURA_CONFIG_PATH, dieses Skript liest sie aus.
 *
 * Bei manueller Ausführung (ohne CURA_CONFIG_PATH) werden argv-Argumente
 * geparsed:
 *   PixInsight -r=cura_batch.js --input=<dir> --output=<dir> ...
 *
 * Dieses Skript ist ein DÜNNER WRAPPER um das WeightedBatchPreProcessing (WBPP)-
 * Skript von PixInsight. WBPP übernimmt die komplette Vorverarbeitung:
 *   - Master-Kalibrierung (Bias/Dark/Flat)
 *   - ImageCalibration
 *   - StarAlignment (Registrierung)
 *   - LocalNormalization (optional)
 *   - ImageIntegration (Stacking mit Signal-Gewichtung)
 *   - Drizzle (optional)
 *
 * Alle Frames (Lights + Flats/Darks/Bias) liegen bereits im Input-Verzeichnis
 * (vom Backend per SMB vom NAS geholt und ins ZIP gepackt). WBPP erkennt den
 * Frame-Typ automatisch am Dateinamen-Präfix (Light_, Dark_, Flat_, Bias_).
 *
 * Fallback: Falls WBPP nicht gefunden wird, wird ein vereinfachter
 * manueller Durchlauf (IC → SA → II) ausgeführt.
 */

#feature-id    cura-stro/batch
#feature-label cura-stro Batch-Vorverarbeitung (WBPP-Wrapper)

#include <pjsr/DataType.jsh>

// ─── Parameter laden (Config-Datei oder argv) ───
var inputDir = "";
var outputDir = "";
var infoFile = "";
var wbppPath = "";
var mode = "wbpp";

if (typeof CURA_CONFIG_PATH !== "undefined" && CURA_CONFIG_PATH && !CURA_CONFIG_PATH.isEmpty()) {
    // Aufruf durch Mac-Agent: Config aus JSON-Datei lesen
    console.writeln("Lade Konfiguration aus: " + CURA_CONFIG_PATH);
    try {
        var configText = File.readTextFile(CURA_CONFIG_PATH);
        var config = JSON.parse(configText);
        inputDir  = config.inputDir  || "";
        outputDir = config.outputDir || "";
        infoFile  = config.infoFile  || "";
        wbppPath  = config.wbppPath  || "";
        mode      = config.mode      || "wbpp";
    } catch (e) {
        console.criticalln("Fehler beim Lesen der Config-Datei: " + e);
        throw e;
    }
} else {
    // Manuelle Ausführung: argv parsen
    console.writeln("Keine Config-Datei — parse argv");
    for (var i = 0; i < argc; ++i) {
        var arg = argv[i];
        if (arg.startsWith("--input="))
            inputDir = arg.substring(8);
        else if (arg.startsWith("--output="))
            outputDir = arg.substring(9);
        else if (arg.startsWith("--info="))
            infoFile = arg.substring(7);
        else if (arg.startsWith("--wbpp="))
            wbppPath = arg.substring(7);
        else if (arg.startsWith("--mode="))
            mode = arg.substring(7);
    }
}

if (inputDir.isEmpty() || outputDir.isEmpty()) {
    console.criticalln("cura_batch: --input und --output erforderlich");
    throw new Error("Missing arguments");
}

console.writeln("=== cura-stro Batch (WBPP-Wrapper) ===");
console.writeln("Input:  " + inputDir);
console.writeln("Output: " + outputDir);
console.writeln("WBPP:   " + (wbppPath.isEmpty() ? "(nicht angegeben)" : wbppPath));
console.writeln("Mode:   " + mode);
console.writeln("Calib-Frames sind im Input-Verzeichnis enthalten (keine separaten Pfade nötig)");

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

// ─── Output-Verzeichnis sicherstellen ───
if (!File.directoryExists(outputDir)) {
    File.createDirectory(outputDir, true);
}

// ─── Hilfsfunktionen (früh definiert, für WBPP und Fallback) ───
function listFiles(dir) {
    var files = [];
    var search = new SearchFile;
    search.directory = dir;
    search.pattern = "*";
    search.matchMode = SearchFile.Mode;
    search.recursive = true;
    search.execute();
    for (var i = 0; i < search.length; ++i) {
        if (!search.isDirectory(i)) {
            files.push(search.fullPath(i));
        }
    }
    return files;
}

function classifyFrame(filename) {
    var base = File.extractName(filename);
    var lower = base.toLowerCase();
    if (lower.startsWith("darkflat") || lower.startsWith("darkflat_"))
        return "darkflat";
    if (lower.startsWith("light") || lower.startsWith("light_"))
        return "light";
    if (lower.startsWith("dark") || lower.startsWith("dark_"))
        return "dark";
    if (lower.startsWith("flat") || lower.startsWith("flat_"))
        return "flat";
    if (lower.startsWith("bias") || lower.startsWith("bias_"))
        return "bias";
    return "light";
}

function isImageFile(filename) {
    var ext = File.extractExtension(filename).toLowerCase();
    return ext === "fit" || ext === "fits" || ext === "fts" ||
           ext === "xisf" || ext === "tif" || ext === "tiff";
}

// ─── Versuch 1: WBPP aufrufen ───
var wbppSuccess = false;

if (!wbppPath.isEmpty() && File.exists(wbppPath)) {
    console.writeln("\n--- WeightedBatchPreProcessing (WBPP) ---");
    try {
        // Alle Frames (Lights + Flats/Darks/Bias) liegen bereits im Input-Verzeichnis.
        // WBPP erkennt Frame-Typen automatisch am Dateinamen-Präfix:
        //   Light_*.fit, Dark_*.fit, Flat_*.fit, Bias_*.fit
        console.writeln("Starte WBPP...");
        console.writeln("Input-Verzeichnis: " + inputDir);
        console.writeln("Output-Verzeichnis: " + outputDir);

        // WBPP per ScriptEngine laden und ausführen
        var engine = new ScriptEngine;
        engine.run(wbppPath, [
            "--input=" + inputDir,
            "--output=" + outputDir,
            "--no-gui",
        ]);

        wbppSuccess = true;
        console.writeln("WBPP erfolgreich abgeschlossen");
    } catch (e) {
        console.warningln("WBPP fehlgeschlagen: " + e);
        console.writeln("Fallback auf manuellen Durchlauf...");
        wbppSuccess = false;
    }
} else {
    if (!wbppPath.isEmpty()) {
        console.warningln("WBPP-Skript nicht gefunden: " + wbppPath);
    }
    console.writeln("Fallback auf manuellen Durchlauf...");
}

// ─── Versuch 2: Manueller Durchlauf (Fallback) ───
if (!wbppSuccess) {
    console.writeln("\n--- Manueller Durchlauf (IC → SA → II) ---");

    // Alle Dateien im Input-Verzeichnis sammeln (Lights + Calib-Frames)
    var allFiles = listFiles(inputDir);

    var lights = [], darks = [], flats = [], biases = [], darkflats = [];

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

    function basename(path) {
        return File.extractName(path) + "." + File.extractExtension(path);
    }

    // 1. Master-Frames erstellen (Bias/Dark/Flat)
    var calDir = outputDir + "/calibrated";
    if (!File.directoryExists(calDir))
        File.createDirectory(calDir, true);

    var masterBias = null, masterDark = null, masterFlat = null;

    if (biases.length > 0) {
        console.writeln("Erstelle Bias-Master...");
        var biasInt = new ImageIntegration;
        biasInt.images = biases.map(function(f) { return { path: f, enabled: true }; });
        biasInt.rejection = "NoRejection";
        biasInt.combination = "Average";
        biasInt.normalize = false;
        masterBias = calDir + "/master_bias.xisf";
        biasInt.outputFile = masterBias;
        biasInt.executeGlobal();
    }

    if (darks.length > 0) {
        console.writeln("Erstelle Dark-Master...");
        var darkInt = new ImageIntegration;
        darkInt.images = darks.map(function(f) { return { path: f, enabled: true }; });
        darkInt.rejection = "WinsorizedSigmaClip";
        darkInt.combination = "Average";
        darkInt.normalize = false;
        masterDark = calDir + "/master_dark.xisf";
        darkInt.outputFile = masterDark;
        darkInt.executeGlobal();
    }

    if (flats.length > 0) {
        console.writeln("Erstelle Flat-Master...");
        var flatInt = new ImageIntegration;
        flatInt.images = flats.map(function(f) { return { path: f, enabled: true }; });
        flatInt.rejection = "WinsorizedSigmaClip";
        flatInt.combination = "Average";
        flatInt.normalize = true;
        masterFlat = calDir + "/master_flat.xisf";
        flatInt.outputFile = masterFlat;
        flatInt.executeGlobal();
    }

    // 2. ImageCalibration
    console.writeln("\n--- ImageCalibration ---");
    var calibratedLights = [];

    var ic = new ImageCalibration;
    ic.enableCFA = false;
    ic.overscanEnabled = false;

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

    ic.targetFrames = lights.map(function(f) {
        return { enabled: true, path: f };
    });
    ic.outputDir = calDir;
    ic.outputExtension = ".xisf";
    ic.overwriteExistingFiles = true;
    ic.executeGlobal();

    for (var i = 0; i < lights.length; ++i) {
        var calName = basename(lights[i]).replace(/\.(fit|fits|fts|xisf|tif|tiff)$/i, ".xisf");
        calibratedLights.push(calDir + "/" + calName);
    }
    console.writeln("Kalibriert: " + calibratedLights.length + " Frames");

    // 3. StarAlignment
    console.writeln("\n--- StarAlignment ---");
    var alignedDir = outputDir + "/aligned";
    if (!File.directoryExists(alignedDir))
        File.createDirectory(alignedDir, true);

    var sa = new StarAlignment;
    sa.referenceImage = calibratedLights[0];
    sa.targetFrames = calibratedLights.map(function(f) {
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

    // 4. ImageIntegration
    console.writeln("\n--- ImageIntegration ---");
    var masterName = "master_" +
        (frameInfo.object_name || "result") + "_" +
        (frameInfo.filter_name || "L") + ".xisf";
    var masterPath = outputDir + "/" + masterName;

    var ii = new ImageIntegration;
    ii.images = alignedLights.map(function(f) {
        return { enabled: true, path: f };
    });
    ii.rejection = "WinsorizedSigmaClip";
    ii.combination = "Average";
    ii.normalize = true;
    ii.weighting = "SignalWeight";
    ii.outputFile = masterPath;
    ii.executeGlobal();

    console.writeln("Master: " + masterPath);
}

// ─── Abschluss ───
console.writeln("\n=== Batch abgeschlossen ===");
console.writeln("Output-Verzeichnis: " + outputDir);
console.writeln("Ergebnisse können nun in PixInsight manuell weiterentwickelt werden.");
