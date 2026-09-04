#target photoshop
var OTRIS_JSX_VERSION = "2026-09-04.2";

(function () {
    if (typeof app === "undefined" || !app.documents) {
        return;
    }

    try {
        $.level = 0;
    } catch (eLevel) {}

    var gJobLogPath = null;

    function readJson(file) {
        if (!file.exists) {
            throw new Error("Job file not found: " + file.fsName);
        }
        file.encoding = "UTF-8";
        file.open("r");
        var raw = file.read();
        file.close();
        return eval("(" + raw + ")");
    }

    function writeLog(jobPath, msg) {
        var path = jobPath || gJobLogPath;
        if (!path) {
            return;
        }
        try {
            var f = new File(String(path) + ".log");
            f.encoding = "UTF-8";
            f.open("a");
            f.writeln(msg);
            f.close();
        } catch (e) {}
    }

    function collectTextLayers(container, out, directOnly) {
        var layers = container.layers;
        for (var i = layers.length - 1; i >= 0; i--) {
            var layer = layers[i];
            if (layer.typename === "ArtLayer" && layer.kind === LayerKind.TEXT) {
                out.push(layer);
            } else if (!directOnly && layer.typename === "LayerSet") {
                collectTextLayers(layer, out, false);
            }
        }
    }

    function findLayerByName(container, name) {
        var layers = container.layers;
        for (var i = 0; i < layers.length; i++) {
            var layer = layers[i];
            if (layer.name === name) {
                return layer;
            }
            if (layer.typename === "LayerSet") {
                var found = findLayerByName(layer, name);
                if (found) {
                    return found;
                }
            }
        }
        return null;
    }

    function setTextPreserveStyle(layer, text, visible) {
        if (visible === false || text === null || text === undefined || text === "") {
            layer.visible = false;
            return;
        }
        layer.visible = true;
        var ti = layer.textItem;
        var oldText = ti.contents;
        var oldSize = ti.size;
        var oldFont = ti.font;
        var oldTracking = ti.tracking;
        var newText = String(text);

        try {
            ti.contents = newText;
        } catch (e1) {
            try {
                ti.contents = newText.substring(0, 200);
            } catch (e2) {
                return;
            }
        }

        try {
            ti.font = oldFont;
        } catch (e3) {}

        if (newText.length > oldText.length * 1.2 && oldText.length > 0) {
            try {
                var ratio = oldText.length / newText.length;
                ti.size = Math.max(oldSize * ratio * 0.96, oldSize * 0.72);
            } catch (e4) {}
        } else {
            try {
                ti.size = oldSize;
            } catch (e5) {}
        }

        try {
            ti.tracking = oldTracking;
        } catch (e6) {}
    }

    function setTextSafe(layer, text, visible) {
        setTextPreserveStyle(layer, text, visible);
    }

    function setLayerFont(layer, psName, job) {
        if (!psName || !layer || layer.kind !== LayerKind.TEXT) {
            return;
        }
        var names = [String(psName)];
        if (job && job.fonts && job.fonts.aliases && job.fonts.aliases[psName]) {
            names = job.fonts.aliases[psName].concat(names);
        }
        if (job && job.fonts && job.fonts.catalog) {
            for (var id in job.fonts.catalog) {
                if (job.fonts.catalog.hasOwnProperty(id)) {
                    var entry = job.fonts.catalog[id];
                    if (entry.postscript === psName && entry.aliases) {
                        names = entry.aliases.concat(names);
                    }
                }
            }
        }
        var seen = {};
        for (var i = 0; i < names.length; i++) {
            var candidate = names[i];
            if (!candidate || seen[candidate]) {
                continue;
            }
            seen[candidate] = true;
            try {
                layer.textItem.font = candidate;
                return;
            } catch (e) {}
        }
    }

    function applyFontRules(doc, job) {
        if (!job || !job.fonts) {
            return;
        }
        var byName = job.fonts.by_layer_name || {};
        if (byName) {
            var layers = [];
            collectTextLayers(doc, layers, false);
            for (var i = 0; i < layers.length; i++) {
                var layer = layers[i];
                if (byName.hasOwnProperty(layer.name)) {
                    setLayerFont(layer, byName[layer.name], job);
                }
            }
        }
        if (job.fonts.text_group_postscript) {
            var groups = [];
            findGroupsNamed(doc, "Text", groups);
            for (var g = 0; g < groups.length; g++) {
                var textLayers = [];
                collectTextLayers(groups[g], textLayers, true);
                for (var t = 0; t < textLayers.length; t++) {
                    setLayerFont(textLayers[t], job.fonts.text_group_postscript, job);
                }
            }
        }
    }

    function updateNamedTextLayers(doc, byName) {
        var layers = [];
        collectTextLayers(doc, layers, false);
        for (var i = 0; i < layers.length; i++) {
            var layer = layers[i];
            if (byName.hasOwnProperty(layer.name)) {
                setTextSafe(layer, byName[layer.name], true);
            }
        }
    }

    function updateTextGroupByIndex(doc, values, visibility) {
        if (!values || !values.length) {
            return;
        }
        var groups = [];
        findGroupsNamed(doc, "Text", groups);
        for (var g = 0; g < groups.length; g++) {
            var textLayers = [];
            collectTextLayers(groups[g], textLayers, true);
            for (var i = 0; i < textLayers.length; i++) {
                var val = i < values.length ? values[i] : "";
                var vis = !visibility || i >= visibility.length ? true : visibility[i];
                setTextSafe(textLayers[i], val, vis);
            }
        }
    }

    function findGroupsNamed(container, name, out) {
        var layers = container.layers;
        for (var i = 0; i < layers.length; i++) {
            var layer = layers[i];
            if (layer.typename === "LayerSet" && layer.name === name) {
                out.push(layer);
            }
            if (layer.typename === "LayerSet") {
                findGroupsNamed(layer, name, out);
            }
        }
    }

    function applyCategoryVisibility(doc, catVis, byName) {
        if (!catVis) {
            return;
        }
        for (var layerName in catVis) {
            if (!catVis.hasOwnProperty(layerName)) {
                continue;
            }
            var layer = findLayerByName(doc, layerName);
            if (!layer) {
                continue;
            }
            if (catVis[layerName]) {
                layer.visible = true;
                if (byName && byName.hasOwnProperty(layerName)) {
                    setTextSafe(layer, byName[layerName], true);
                }
            } else {
                layer.visible = false;
            }
        }
    }

    function setLayerVisible(layer, visible) {
        layer.visible = !!visible;
    }

    function normalizePath(p) {
        return String(p).replace(/\\/g, "/").toLowerCase();
    }

    function docName(doc) {
        try {
            return String(doc.name);
        } catch (e) {
            return "";
        }
    }

    function findOpenDoc(templatePath) {
        var want = normalizePath(templatePath);
        for (var i = 0; i < app.documents.length; i++) {
            try {
                var d = app.documents[i];
                if (normalizePath(d.fullName.fsName) === want) {
                    return d;
                }
            } catch (e) {}
        }
        return null;
    }

    function docExists(name) {
        if (!name) {
            return false;
        }
        for (var i = 0; i < app.documents.length; i++) {
            try {
                if (app.documents[i].name === name) {
                    return true;
                }
            } catch (e) {}
        }
        return false;
    }

    function activateByName(name) {
        if (!name) {
            return false;
        }
        for (var i = 0; i < app.documents.length; i++) {
            try {
                var d = app.documents[i];
                if (d.name === name) {
                    app.activeDocument = d;
                    return true;
                }
            } catch (e) {}
        }
        return false;
    }

    function closeActive(saveChanges) {
        try {
            var desc = new ActionDescriptor();
            desc.putEnumerated(
                stringIDToTypeID("saving"),
                stringIDToTypeID("yesNo"),
                stringIDToTypeID(saveChanges ? "yes" : "no")
            );
            executeAction(stringIDToTypeID("close"), desc, DialogModes.NO);
            return;
        } catch (eSid) {}
        try {
            var desc2 = new ActionDescriptor();
            desc2.putEnumerated(
                charIDToTypeID("Svng"),
                charIDToTypeID("YsN "),
                charIDToTypeID(saveChanges ? "yes " : "no  ")
            );
            executeAction(charIDToTypeID("Cls "), desc2, DialogModes.NO);
        } catch (eCid) {
            app.activeDocument.close(
                saveChanges ? SaveOptions.SAVECHANGES : SaveOptions.DONOTSAVECHANGES
            );
        }
    }

    function closeByName(name) {
        if (!name || !activateByName(name)) {
            return;
        }
        try {
            closeActive(false);
            return;
        } catch (e1) {}
        try {
            app.activeDocument.close(SaveOptions.DONOTSAVECHANGES);
        } catch (e2) {}
    }

    function uniqueWorkName(job) {
        var base = "vu_" + String(job.job_id || "render").replace(/[^a-zA-Z0-9_-]/g, "");
        var name = base;
        var n = 1;
        while (docExists(name)) {
            name = base + "_" + n;
            n++;
        }
        return name;
    }

    function openJobDocument(job, templateFile) {
        var templateDoc = findOpenDoc(job.template);
        if (!templateDoc) {
            templateDoc = app.open(templateFile);
        }
        var templateName = docName(templateDoc);
        var workName = uniqueWorkName(job);
        var isDuplicate = false;

        try {
            app.activeDocument = templateDoc;
            templateDoc.duplicate(workName, false);
            workName = docName(app.activeDocument) || workName;
            isDuplicate = true;
        } catch (eDup) {
            writeLog(null, "duplicate failed, working on template: " + eDup);
            workName = templateName;
            isDuplicate = false;
            try {
                app.activeDocument = templateDoc;
            } catch (eAct) {}
        }

        if (isDuplicate && !job.keep_template_open) {
            try {
                closeByName(templateName);
            } catch (eCloseTpl) {
                writeLog(null, "template close skipped: " + eCloseTpl);
            }
        }

        return {
            workName: workName,
            templateName: templateName,
            isDuplicate: isDuplicate
        };
    }

    function forEachLayerByName(container, name, fn) {
        var layers = container.layers;
        for (var i = 0; i < layers.length; i++) {
            var layer = layers[i];
            if (layer.name === name) {
                fn(layer);
            }
            if (layer.typename === "LayerSet") {
                forEachLayerByName(layer, name, fn);
            }
        }
    }

    function applyBackground(doc, job) {
        if (!job.background || !job.scene) {
            return;
        }
        var prefix = job.scene.background_prefix || "Вариант ";
        var count = job.scene.background_count || 10;
        for (var i = 1; i <= count; i++) {
            var layerName = prefix + i;
            forEachLayerByName(doc, layerName, function (layer) {
                setLayerVisible(layer, i === job.background);
            });
        }
    }

    function applyMockupVariant(doc, job) {
        if (!job.mockup_variant || !job.scene) {
            return;
        }
        var hand = job.scene.hand_group;
        var orig = job.scene.original_layer;
        if (job.mockup_variant === "hand") {
            if (orig) {
                forEachLayerByName(doc, orig, function (layer) {
                    setLayerVisible(layer, false);
                });
            }
            if (hand) {
                forEachLayerByName(doc, hand, function (layer) {
                    setLayerVisible(layer, true);
                });
            }
        } else if (job.mockup_variant === "original") {
            if (hand) {
                forEachLayerByName(doc, hand, function (layer) {
                    setLayerVisible(layer, false);
                });
            }
            if (orig) {
                forEachLayerByName(doc, orig, function (layer) {
                    setLayerVisible(layer, true);
                });
            }
        }
    }

    function scaleLayerToCanvas(doc) {
        try {
            var b = doc.activeLayer.bounds;
            var w = b[2].as("px") - b[0].as("px");
            var h = b[3].as("px") - b[1].as("px");
            var cw = doc.width.as("px");
            var ch = doc.height.as("px");
            if (w <= 0 || h <= 0) {
                return;
            }
            var scale = Math.max(cw / w, ch / h) * 100;
            doc.activeLayer.resize(scale, scale, AnchorPosition.MIDDLECENTER);
        } catch (e) {}
    }

    function placeImageInDoc(doc, imagePath) {
        var file = new File(imagePath);
        if (!file.exists) {
            return;
        }
        try {
            app.activeDocument = doc;
        } catch (eAct) {}
        var desc = new ActionDescriptor();
        desc.putPath(charIDToTypeID("null"), file);
        desc.putEnumerated(charIDToTypeID("FTcs"), charIDToTypeID("QCSt"), charIDToTypeID("Qcsa"));
        try {
            desc.putBoolean(charIDToTypeID("Lnkd"), false);
        } catch (eLnk) {}
        try {
            executeAction(charIDToTypeID("Plc "), desc, DialogModes.NO);
        } catch (ePlc) {
            try {
                var desc2 = new ActionDescriptor();
                desc2.putPath(charIDToTypeID("null"), file);
                executeAction(stringIDToTypeID("placeEvent"), desc2, DialogModes.NO);
            } catch (ePlc2) {
                return;
            }
        }
        scaleLayerToCanvas(doc);
    }

    function scaleActiveLayerCover(doc) {
        var layer = doc.activeLayer;
        var b = layer.bounds;
        var w = b[2].as("px") - b[0].as("px");
        var h = b[3].as("px") - b[1].as("px");
        var cw = doc.width.as("px");
        var ch = doc.height.as("px");
        if (w <= 0 || h <= 0) {
            return;
        }
        var scale = Math.max(cw / w, ch / h) * 100;
        layer.resize(scale, scale, AnchorPosition.MIDDLECENTER);
        b = layer.bounds;
        var cx = (b[0].as("px") + b[2].as("px")) / 2;
        var cy = (b[1].as("px") + b[3].as("px")) / 2;
        layer.translate(cw / 2 - cx, ch / 2 - cy);
    }

    function replacePortrait(layer, imagePath, job) {
        editSmartObject(layer, function (innerDoc) {
            var before = innerDoc.layers.length;
            placeImageInDoc(innerDoc, imagePath);
            if (innerDoc.layers.length <= before) {
                writeLog(null, "portrait place failed: " + imagePath);
                return;
            }
            scaleActiveLayerCover(innerDoc);
            try {
                while (innerDoc.layers.length > 1) {
                    innerDoc.layers[innerDoc.layers.length - 1].remove();
                }
            } catch (eRm) {}
        });
    }

    function editSmartObject(layer, fn) {
        var parentName = docName(app.activeDocument);
        try {
            app.activeDocument.activeLayer = layer;
        } catch (eSel) {
            return;
        }
        var innerName = "";
        var opened = false;
        try {
            try {
                var desc = new ActionDescriptor();
                executeAction(stringIDToTypeID("placedLayerEditContents"), desc, DialogModes.NO);
            } catch (eDesc) {
                if (docName(app.activeDocument) === parentName) {
                    executeAction(stringIDToTypeID("placedLayerEditContents"), undefined, DialogModes.NO);
                }
            }
            innerName = docName(app.activeDocument);
            if (!innerName || innerName === parentName) {
                return;
            }
            opened = true;
            fn(app.activeDocument);
        } catch (eEdit) {
            writeLog(null, "smart object skipped (" + layer.name + "): " + eEdit);
        } finally {
            if (opened && innerName && innerName !== parentName && activateByName(innerName)) {
                try {
                    closeActive(true);
                } catch (eClose1) {
                    try {
                        app.activeDocument.close(SaveOptions.SAVECHANGES);
                    } catch (eClose2) {
                        try {
                            app.activeDocument.save();
                            closeActive(false);
                        } catch (eClose3) {}
                    }
                }
            }
            activateByName(parentName);
        }
    }

    function isSmartObject(layer) {
        try {
            return layer.kind === LayerKind.SMARTOBJECT;
        } catch (e) {
            return false;
        }
    }

    function walkLayers(layers, job, depth) {
        if (depth > 6) {
            return;
        }
        for (var i = 0; i < layers.length; i++) {
            var layer = layers[i];
            if (layer.typename === "LayerSet") {
                walkLayers(layer.layers, job, depth);
            } else if (layer.typename === "ArtLayer" && isSmartObject(layer)) {
                var scene = job.scene || {};
                var isBg = scene.background_smart_object && layer.name === scene.background_smart_object;
                var isPhoto = scene.photo_smart_object && layer.name === scene.photo_smart_object;
                try {
                    if (isPhoto && job.portrait_path) {
                        replacePortrait(layer, job.portrait_path, job);
                    } else if (isBg) {
                        editSmartObject(layer, function (innerDoc) {
                            applyBackground(innerDoc, job);
                        });
                    } else {
                        editSmartObject(layer, function (innerDoc) {
                            applyJob(innerDoc, job, depth + 1);
                        });
                    }
                } catch (eSO) {
                    writeLog(null, "walkLayers skip " + layer.name + ": " + eSO);
                }
            }
        }
    }

    function applyJob(doc, job, depth) {
        applyMockupVariant(doc, job);
        var byName = job.layers_by_name || {};
        updateNamedTextLayers(doc, byName);
        applyCategoryVisibility(doc, job.category_visibility || null, byName);
        updateTextGroupByIndex(doc, job.text_group_values || [], job.text_group_visibility || null);
        applyFontRules(doc, job);
        walkLayers(doc.layers, job, depth || 0);
    }

    function saveMasterAM(file, isPsb, asCopy) {
        var desc = new ActionDescriptor();
        var fmt = new ActionDescriptor();
        try {
            fmt.putBoolean(stringIDToTypeID("maximizeCompatibility"), true);
        } catch (eMc) {}
        var typeId = isPsb ? stringIDToTypeID("largeDocumentFormat") : charIDToTypeID("Pht3");
        desc.putObject(charIDToTypeID("As  "), typeId, fmt);
        desc.putPath(charIDToTypeID("In  "), file);
        desc.putBoolean(charIDToTypeID("Cpy "), !!asCopy);
        try {
            desc.putBoolean(charIDToTypeID("LwCs"), true);
        } catch (eLc) {}
        executeAction(charIDToTypeID("save"), desc, DialogModes.NO);
    }

    function saveMasterByName(workName, file, isPsb, asCopy) {
        if (!activateByName(workName)) {
            throw new Error("Work document not found: " + workName);
        }
        var opts = new PhotoshopSaveOptions();
        opts.layers = true;
        opts.embedColorProfile = true;
        try {
            opts.maximizeCompatibility = true;
        } catch (eMc) {}
        try {
            app.activeDocument.saveAs(file, opts, !!asCopy, Extension.LOWERCASE);
        } catch (eSave) {
            writeLog(null, "saveAs DOM failed, Action Manager: " + eSave);
            saveMasterAM(file, isPsb, asCopy);
        }
        if (asCopy) {
            return workName;
        }
        var savedName = "";
        try {
            savedName = docName(app.activeDocument);
        } catch (eName) {}
        return savedName || file.name;
    }

    function jpegOptions() {
        var opts = new JPEGSaveOptions();
        opts.quality = 12;
        opts.embedColorProfile = true;
        opts.formatOptions = FormatOptions.STANDARDBASELINE;
        try {
            opts.matte = MatteType.NONE;
        } catch (eM) {}
        return opts;
    }

    function exportJpegByName(workName, file) {
        if (!activateByName(workName)) {
            throw new Error("Work document not found for JPEG: " + workName);
        }
        var opts = jpegOptions();
        try {
            app.activeDocument.saveAs(file, opts, true, Extension.LOWERCASE);
            if (fileReady(file)) {
                return;
            }
        } catch (eJpg) {
            writeLog(null, "jpeg as-copy failed: " + eJpg);
        }

        var dupName = "_vu_jpg_" + (new Date().getTime());
        var actual = "";
        try {
            if (!activateByName(workName)) {
                throw new Error("Work document lost before JPEG flatten");
            }
            app.activeDocument.duplicate(dupName, true);
            actual = docName(app.activeDocument) || dupName;
            try {
                app.activeDocument.flatten();
            } catch (eFlat) {}
            app.activeDocument.saveAs(file, opts, true, Extension.LOWERCASE);
        } finally {
            closeByName(actual || dupName);
            if (actual && actual !== dupName) {
                closeByName(dupName);
            }
            activateByName(workName);
        }
    }

    function fileReady(f) {
        try {
            return f.exists && f.length > 0;
        } catch (e) {
            return f.exists;
        }
    }

    function outputsExist(psdFile, jpgFile) {
        return fileReady(psdFile) && fileReady(jpgFile);
    }

    function main() {
        var jobPath = (typeof OTRIS_JOB_PATH !== "undefined")
            ? OTRIS_JOB_PATH
            : $.getenv("OTRIS_JOB");
        if (!jobPath) {
            throw new Error("OTRIS_JOB_PATH / OTRIS_JOB is not set");
        }
        gJobLogPath = jobPath;
        writeLog(jobPath, "jsx " + OTRIS_JSX_VERSION);
        var job = readJson(new File(jobPath));
        var templateFile = new File(job.template);
        var psdFile = new File(job.output_psd);
        var jpgFile = new File(job.output_jpg);
        var isPsb = job.output_is_psb === true || /\.psb$/i.test(job.template);

        var opened = openJobDocument(job, templateFile);
        var workName = opened.workName;
        var renderError = null;

        try {
            if (!activateByName(workName)) {
                throw new Error("Work document is not open: " + workName);
            }
            applyJob(app.activeDocument, job);
            workName = saveMasterByName(workName, psdFile, isPsb, !opened.isDuplicate);
            exportJpegByName(workName, jpgFile);
        } catch (e) {
            renderError = e;
            writeLog(jobPath, "render error: " + e);
        }

        try {
            if (opened.isDuplicate || !job.keep_template_open) {
                closeByName(workName);
            }
        } catch (eClose) {
            writeLog(jobPath, "close warn: " + eClose);
        }

        if (outputsExist(psdFile, jpgFile)) {
            writeLog(jobPath, "ok");
            return;
        }
        if (renderError) {
            throw renderError;
        }
        throw new Error("Output files were not created: " + psdFile.fsName);
    }

    try {
        app.displayDialogs = DialogModes.NO;
        try {
            app.playbackDisplayDialogs = DialogModes.NO;
        } catch (ePd) {}
        app.preferences.rulerUnits = Units.PIXELS;
        main();
    } catch (eMain) {
        writeLog(gJobLogPath, "uncaught: " + eMain);
        if (!gJobLogPath) {
            throw eMain;
        }
    }
})();
