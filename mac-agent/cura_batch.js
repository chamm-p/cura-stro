/* cura_batch.js — PixInsight PJSR Batch-Skript (WBPP-Wrapper)
 *
 * Wird headless vom Mac-Agent aufgerufen:
 *   PixInsight -run=cura_batch.js --input=<dir> --output=<dir> --info=<json> --wbpp=<path> --mode=<wbpp|fastbatch> --calib=<dir> --flats=<dir> --darks=<dir> --bias=<dir>
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
 * WBPP erzeugt pro Filter/Gruppe einen Master-Frame und legt die Ergebnisse
 * (kalibrierte Frames, ausgerichtete Frames, Master-Integration) in einer
 * strukturierten Ordner-Hierarchie ab.
 *
 * Nach WBPP kann der Nutzer in PixInsight manuell weiterarbeiten
 * (Histogramm, Deconvolution, NoiseReduction, ColorCalibration, etc.).
 * cura-stro setzt den Status auf 'vorbereitet' — nicht 'entwickelt'.
 *
 * Fallback: Falls WBPP nicht gefunden wird, wird ein vereinfachter
 * manueller Durchlauf (IC → SA → II) ausgeführt.
 */

#feature-id    cura-stro/batch
#feature-label cura-stro Batch-Vorverarbeitung (WBPP-Wrapper)

#include <pjsr/DataType.jsh>

// ─── Argumente parsen ───
var inputDir = "";
var outputDir = "";
var infoFile = "";
var wbppPath = "";
var mode = "wbpp";
var calibDir = "";   // Legacy: alle Calib-Frames in einem Verzeichnis
var flatsDir = "";   // Separate Verzeichnisse
var darksDir = "";
var biasDir = "";

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
    else if (arg.startsWith("--calib="))
        calibDir = arg.substring(8);
    else if (arg.startsWith("--flats="))
        flatsDir = arg.substring(8);
    else if (arg.startsWith("--darks="))
        darksDir = arg.substring(8);
    else if (arg.startsWith("--bias="))
        biasDir = arg.substring(7);
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
console.writeln("Calib:  " + (calibDir.isEmpty() ? "(keine)" : calibDir));
console.writeln("Flats:  " + (flatsDir.isEmpty() ? "(keine)" : flatsDir));
console.writeln("Darks:  " + (darksDir.isEmpty() ? "(keine)" : darksDir));
console.writeln("Bias:   " + (biasDir.isEmpty() ? "(keine)" : biasDir));

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
    search.matchMode = SearchFile.Mode递;
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
        // WBPP als externes Skript laden und ausführen
        // WBPP erwartet die Frames in Unterverzeichnissen oder mit passenden
        // Dateinamen. ASIAir-Dateien folgen der Konvention:
        //   Light_<obj>_<exp>s_Bin<n>[_<filter>]_<date>-<time>_<seq>.fit
        //   Dark_<obj>_...
        //   Flat_<obj>_...
        //   Bias_<obj>_...
        //
        // WBPP erkennt Frame-Typen automatisch anhand des Dateinamen-Präfixes.

        // WBPP-Konfiguration über Environment-Variablen / Parameter
        // WBPP kann per Skript konfiguriert werden:
        var wbppScript = File.readTextFile(wbppPath);

        // WBPP-Parameter setzen (über globale Variablen vor dem Laden)
        // Diese Variablen werden von WBPP ausgewertet, wenn es geladen wird.
        // Siehe WBPP-Dokumentation für alle Optionen.

        // Output-Verzeichnis für WBPP setzen
        params = {
            outputDirectory: outputDir,
            inputDirectory: inputDir,
            // Diagnostik
            generateDiagnostiData: false,
            // Kalibrierung
            masterBias: true,
            masterDark: true,
            masterFlat: true,
            // Registrierung
            starAlignment: true,
            // Integration
            imageIntegration: true,
            // Local Normalization (empfohlen für gute Ergebnisse)
            localNormalization: false,  // kann lange dauern
            // Drizzle (nur für hochaufgelöste Daten)
            drizzle: false,
            // Rejection
            rejection: "WinsorizedSigmaClip",
            // Overwrite
            overwriteExistingFiles: true,
        };

        // WBPP-Skript ausführen
        // Hinweis: WBPP lädt seine eigene UI; im headless-Modus wird die
        // Kommandozeilen-Version verwendet.
        console.writeln("Starte WBPP...");
        console.writeln("Input-Verzeichnis: " + inputDir);
        console.writeln("Output-Verzeichnis: " + outputDir);

        // Calibration-Frames in das Input-Verzeichnis kopieren, damit WBPP
        // sie automatisch erkennt (WBPP nutzt Dateinamen-Präfixe).
        var calibDirsToCopy = [
            { path: flatsDir, label: "Flats" },
            { path: darksDir, label: "Darks" },
            { path: biasDir,  label: "Bias"  },
        ];
        if (!calibDir.isEmpty() && flatsDir.isEmpty() && darksDir.isEmpty() && biasDir.isEmpty()) {
            calibDirsToCopy = [{ path: calibDir, label: "Calibration (legacy)" }];
        }
        for (var cd = 0; cd < calibDirsToCopy.length; ++cd) {
            var cdir = calibDirsToCopy[cd].path;
            var clabel = calibDirsToCopy[cd].label;
            if (!cdir.isEmpty() && File.directoryExists(cdir)) {
                console.writeln("Kopiere " + clabel + " in Input-Verzeichnis: " + cdir);
                var calibFiles = listFiles(cdir);
                for (var ci = 0; ci < calibFiles.length; ++ci) {
                    if (isImageFile(calibFiles[ci])) {
                        var destFile = inputDir + "/" + File.extractName(calibFiles[ci]) + "." + File.extractExtension(calibFiles[ci]);
                        File.copy(calibFiles[ci], destFile);
                    }
                }
            } else if (!cdir.isEmpty()) {
                console.warningln(clabel + "-Verzeichnis nicht gefunden: " + cdir);
            }
        }

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

    // Dateien nach Frame-Typ sortieren (Hilfsfunktionen oben definiert)
    var allFiles = listFiles(inputDir);

    // Calibration-Frames aus den jeweiligen Verzeichnissen hinzufügen
    // Separate Verzeichnisse (bevorzugt)
    var calibDirs = [
        { path: flatsDir, label: "Flats" },
        { path: darksDir, label: "Darks" },
        { path: biasDir,  label: "Bias"  },
    ];
    // Legacy-Fallback: calibDir für alle verwenden, wenn keine separaten gesetzt
    if (!calibDir.isEmpty() && flatsDir.isEmpty() && darksDir.isEmpty() && biasDir.isEmpty()) {
        calibDirs = [{ path: calibDir, label: "Calibration (legacy)" }];
    }
    for (var cd = 0; cd < calibDirs.length; ++cd) {
        var cdir = calibDirs[cd].path;
        var clabel = calibDirs[cd].label;
        if (!cdir.isEmpty() && File.directoryExists(cdir)) {
            console.writeln("Lade " + clabel + " aus: " + cdir);
            var calibFiles = listFiles(cdir);
            for (var ci = 0; ci < calibFiles.length; ++ci) {
                if (isImageFile(calibFiles[ci])) {
                    allFiles.push(calibFiles[ci]);
                }
            }
        } else if (!cdir.isEmpty()) {
            console.warningln(clabel + "-Verzeichnis nicht gefunden: " + cdir);
        }
    }

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
