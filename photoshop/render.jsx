#target photoshop

(function () {
    if (typeof app === "undefined" || !app.documents) {
        return;
    }

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

    function findOpenDoc(templatePath) {
        var want = normalizePath(templatePath);
        for (var i = 0; i < app.documents.length; i++) {
            var d = app.documents[i];
            try {
                if (normalizePath(d.fullName.fsName) === want) {
                    return d;
                }
            } catch (e) {}
        }
        return null;
    }

    function openJobDocument(job, templateFile) {
        var workDoc = null;
        var templateDoc = null;

        if (job.reuse_open_template) {
            templateDoc = findOpenDoc(job.template);
            if (templateDoc) {
                workDoc = templateDoc.duplicate("vu_" + (job.job_id || "render"), false);
            }
        }

        if (!workDoc) {
            workDoc = app.open(templateFile);
            if (job.keep_template_open && !job.reuse_open_template) {
                templateDoc = workDoc;
            }
        }

        return { work: workDoc, template: templateDoc };
    }

    function docName(doc) {
        try {
            return String(doc.name);
        } catch (e) {
            return "";
        }
    }

    function docIsOpen(doc) {
        var name = docName(doc);
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

    function closeDocByName(name) {
        if (!name) {
            return;
        }
        for (var i = app.documents.length - 1; i >= 0; i--) {
            try {
                var d = app.documents[i];
                if (d.name === name) {
                    d.close(SaveOptions.DONOTSAVECHANGES);
                    return;
                }
            } catch (e) {}
        }
    }

    function closeJobDocument(workDoc, templateDoc, job) {
        try {
            var name = docName(workDoc);
            if (!name || !docIsOpen(workDoc)) {
                return;
            }
            var isDuplicate = name.indexOf("vu_") === 0 || name.indexOf("_vu_") === 0;
            if (isDuplicate || !job.keep_template_open) {
                closeDocByName(name);
            }
        } catch (e) {
            // PS 2025/2026 may throw on stale document handles after saveAs.
        }
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
        var idPlc = charIDToTypeID("Plc ");
        var desc = new ActionDescriptor();
        desc.putPath(charIDToTypeID("null"), file);
        desc.putEnumerated(charIDToTypeID("FTcs"), charIDToTypeID("QCSt"), charIDToTypeID("Qcsa"));
        executeAction(idPlc, desc, DialogModes.NO);
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
            while (innerDoc.layers.length > 0) {
                innerDoc.layers[0].remove();
            }
            placeImageInDoc(innerDoc, imagePath);
            scaleActiveLayerCover(innerDoc);
        });
    }

    function editSmartObject(layer, fn) {
        var parentName = docName(app.activeDocument);
        app.activeDocument.activeLayer = layer;
        var id = stringIDToTypeID("placedLayerEditContents");
        executeAction(id, undefined, DialogModes.NO);
        var innerDoc = app.activeDocument;
        var innerName = docName(innerDoc);
        try {
            fn(innerDoc);
        } finally {
            try {
                if (docIsOpen(innerDoc)) {
                    innerDoc.close(SaveOptions.SAVECHANGES);
                } else {
                    closeDocByName(innerName);
                }
            } catch (e1) {}
            try {
                for (var i = 0; i < app.documents.length; i++) {
                    if (app.documents[i].name === parentName) {
                        app.activeDocument = app.documents[i];
                        break;
                    }
                }
            } catch (e2) {}
        }
    }

    function walkLayers(layers, job) {
        for (var i = 0; i < layers.length; i++) {
            var layer = layers[i];
            if (layer.typename === "LayerSet") {
                walkLayers(layer.layers, job);
            } else if (layer.typename === "ArtLayer") {
                if (layer.kind === LayerKind.SMARTOBJECT) {
                    var scene = job.scene || {};
                    var isBg = scene.background_smart_object && layer.name === scene.background_smart_object;
                    var isPhoto = scene.photo_smart_object && layer.name === scene.photo_smart_object;

                    if (isPhoto && job.portrait_path) {
                        replacePortrait(layer, job.portrait_path, job);
                    } else if (isBg) {
                        editSmartObject(layer, function (innerDoc) {
                            applyBackground(innerDoc, job);
                        });
                    } else {
                        editSmartObject(layer, function (innerDoc) {
                            applyJob(innerDoc, job);
                        });
                    }
                }
            }
        }
    }

    function applyJob(doc, job) {
        applyMockupVariant(doc, job);
        var byName = job.layers_by_name || {};
        updateNamedTextLayers(doc, byName);
        applyCategoryVisibility(doc, job.category_visibility || null, byName);
        updateTextGroupByIndex(doc, job.text_group_values || [], job.text_group_visibility || null);
        applyFontRules(doc, job);
        walkLayers(doc.layers, job);
    }

    function exportJpeg(doc, file) {
        var parentName = docName(doc);
        var dupName = "_vu_jpg_" + (new Date().getTime());
        var dup = null;
        try {
            app.activeDocument = doc;
            dup = doc.duplicate(dupName, true);
            dup.flatten();
            var opts = new JPEGSaveOptions();
            opts.quality = 12;
            opts.embedColorProfile = true;
            opts.formatOptions = FormatOptions.STANDARDBASELINE;
            dup.saveAs(file, opts, true, Extension.LOWERCASE);
        } finally {
            closeDocByName(dupName);
            try {
                for (var i = 0; i < app.documents.length; i++) {
                    if (app.documents[i].name === parentName) {
                        app.activeDocument = app.documents[i];
                        break;
                    }
                }
            } catch (e) {}
        }
    }

    function saveMaster(doc, file, isPsb) {
        app.activeDocument = doc;
        if (isPsb) {
            var psbOpts = new PhotoshopSaveOptions();
            psbOpts.layers = true;
            psbOpts.embedColorProfile = true;
            doc.saveAs(file, psbOpts, true, Extension.LOWERCASE);
        } else {
            var psdOpts = new PhotoshopSaveOptions();
            psdOpts.layers = true;
            psdOpts.embedColorProfile = true;
            doc.saveAs(file, psdOpts, true, Extension.LOWERCASE);
        }
    }

    function main() {
        var jobPath = (typeof OTRIS_JOB_PATH !== "undefined")
            ? OTRIS_JOB_PATH
            : $.getenv("OTRIS_JOB");
        if (!jobPath) {
            throw new Error("OTRIS_JOB_PATH / OTRIS_JOB is not set");
        }
        var job = readJson(new File(jobPath));
        var templateFile = new File(job.template);
        var psdFile = new File(job.output_psd);
        var jpgFile = new File(job.output_jpg);
        var isPsb = job.output_is_psb === true || /\.psb$/i.test(job.template);

        var opened = openJobDocument(job, templateFile);
        var doc = opened.work;
        var workName = docName(doc);
        try {
            applyJob(doc, job);
            saveMaster(doc, psdFile, isPsb);
            exportJpeg(doc, jpgFile);
        } finally {
            try {
                closeJobDocument(doc, opened.template, job);
            } catch (cleanupErr) {}
            // Fallback for PS 2026 stale handles: close by saved name.
            try {
                if (workName && workName.indexOf("vu_") === 0) {
                    closeDocByName(workName);
                }
            } catch (cleanupErr2) {}
        }
    }

    app.displayDialogs = DialogModes.NO;
    app.preferences.rulerUnits = Units.PIXELS;
    main();
})();
