#target photoshop
var OTRIS_JSX_VERSION = "2026-09-05.21";

(function () {
    if (typeof app === "undefined" || !app.documents) {
        return;
    }

    try {
        $.level = 0;
    } catch (eLevel) {}

    var gJobLogPath = null;
    var gWorkName = "";
    var gTemplateName = "";

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

    function mapHas(obj, key) {
        if (!obj || key === undefined || key === null) {
            return false;
        }
        try {
            return obj[key] !== undefined && obj[key] !== null;
        } catch (e) {
            return false;
        }
    }

    function mapGet(obj, key) {
        try {
            return obj[key];
        } catch (e) {
            return undefined;
        }
    }

    function isTextLayer(layer) {
        try {
            if (layer.typename !== "ArtLayer") {
                return false;
            }
        } catch (eType) {
            return false;
        }
        try {
            return layer.kind === LayerKind.TEXT;
        } catch (eKind) {
            try {
                return layer.textItem !== null && layer.textItem !== undefined;
            } catch (eTi) {
                return false;
            }
        }
    }

    function collectTextLayers(container, out, directOnly, skipGroupName) {
        var layers;
        try {
            layers = container.layers;
        } catch (eLayers) {
            return;
        }
        for (var i = layers.length - 1; i >= 0; i--) {
            var layer = layers[i];
            var typename = "";
            try {
                typename = layer.typename;
            } catch (eType) {
                continue;
            }
            if (isTextLayer(layer)) {
                out.push(layer);
            } else if (!directOnly && typename === "LayerSet") {
                var gname = "";
                try {
                    gname = String(layer.name);
                } catch (eG) {}
                if (skipGroupName && gname === skipGroupName) {
                    continue;
                }
                collectTextLayers(layer, out, false, skipGroupName);
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

    function layerNameKey(n) {
        return String(n || "").replace(/^\s+|\s+$/g, "").toLowerCase();
    }

    function photoAliases(job) {
        var list = ["photo", "фото", "portrait", "портрет", "id photo", "idphoto"];
        var scene = (job && job.scene) || {};
        if (scene.photo_smart_object) {
            list.unshift(layerNameKey(scene.photo_smart_object));
        }
        var extra = scene.photo_layer_aliases;
        if (extra) {
            for (var i = 0; i < extra.length; i++) {
                list.push(layerNameKey(extra[i]));
            }
        }
        return list;
    }

    function isPhotoName(n, job) {
        var raw = String(n || "");
        var k = layerNameKey(raw);
        var aliases = photoAliases(job);
        for (var i = 0; i < aliases.length; i++) {
            if (k === aliases[i]) {
                return true;
            }
        }
        return /photo|фото|portrait|портрет/i.test(raw);
    }

    function layerAspect(layer) {
        try {
            var b = layer.bounds;
            var w = b[2].as("px") - b[0].as("px");
            var h = b[3].as("px") - b[1].as("px");
            if (h <= 1 || w <= 1) {
                return 0;
            }
            return w / h;
        } catch (e) {
            return 0;
        }
    }

    function layerLeft(layer) {
        try {
            return layer.bounds[0].as("px");
        } catch (e) {
            return 99999;
        }
    }

    function isPhotoCandidateKind(layer) {
        if (isTextLayer(layer)) {
            return false;
        }
        try {
            if (layer.kind === LayerKind.SOLIDFILL || layer.kind === LayerKind.GRADIENTFILL) {
                return false;
            }
        } catch (eKind) {}
        return true;
    }

    function fileBaseName(p) {
        var s = String(p || "");
        var slash = s.lastIndexOf("\\");
        var fwd = s.lastIndexOf("/");
        if (fwd > slash) {
            slash = fwd;
        }
        return slash >= 0 ? s.substring(slash + 1) : s;
    }

    function isCardFaceDoc(doc, job) {
        var n = docName(doc);
        if (/license|licence/i.test(n)) {
            return true;
        }
        var blank = fileBaseName(job && job.blank_template);
        if (blank) {
            var stem = blank.replace(/\.(psb|psd)$/i, "");
            if (n === blank || (stem && n.indexOf(stem) === 0)) {
                return true;
            }
        }
        return false;
    }

    function isProtectedSceneLayer(layer, job) {
        var n = "";
        try {
            n = String(layer.name);
        } catch (e) {
            return true;
        }
        var scene = (job && job.scene) || {};
        if (scene.background_smart_object && n === scene.background_smart_object) {
            return true;
        }
        if (scene.hand_group && n === scene.hand_group) {
            return true;
        }
        if (scene.original_layer && n === scene.original_layer) {
            return true;
        }
        if (nameInList(n, scene.skip_smart_objects || job.skip_smart_objects)) {
            return true;
        }
        if (nameInList(n, scene.card_wrappers || job.card_wrappers)) {
            return true;
        }
        if (isCardSmartObject(layer, job) || isWrapperSmartObject(layer, job)) {
            return true;
        }
        if (/^(front|back|background|signature|bar\s*code|text)$/i.test(n)) {
            return true;
        }
        return false;
    }

    function collectPhotoCandidates(container, job, out, prefix) {
        var layers;
        try {
            layers = container.layers;
        } catch (e) {
            return;
        }
        for (var i = 0; i < layers.length; i++) {
            var layer = layers[i];
            var typename = "";
            var name = "";
            try {
                typename = layer.typename;
            } catch (eT) {
                continue;
            }
            try {
                name = String(layer.name);
            } catch (eN) {
                name = "?";
            }
            var path = prefix ? prefix + "/" + name : name;
            if (typename === "LayerSet") {
                collectPhotoCandidates(layer, job, out, path);
            } else if (typename === "ArtLayer" && isPhotoCandidateKind(layer)) {
                out.push({ layer: layer, path: path, name: name });
            }
        }
    }

    function findPhotoByName(container, job) {
        var named = [];
        collectPhotoCandidates(container, job, named, "");
        for (var i = 0; i < named.length; i++) {
            if (isPhotoName(named[i].name, job) && !isProtectedSceneLayer(named[i].layer, job)) {
                return named[i];
            }
        }
        return null;
    }

    function findPhotoOnCardFace(doc, job) {
        var named = [];
        collectPhotoCandidates(doc, job, named, "");
        var cw = 0;
        var ch = 0;
        try {
            cw = doc.width.as("px");
            ch = doc.height.as("px");
        } catch (eSz) {
            return null;
        }
        if (cw < 10 || ch < 10) {
            return null;
        }
        var best = null;
        var bestArea = 0;
        for (var i = 0; i < named.length; i++) {
            var item = named[i];
            if (!isVisible(item.layer) || isProtectedSceneLayer(item.layer, job)) {
                continue;
            }
            var b;
            var w = 0;
            var h = 0;
            var cx = 0;
            try {
                b = item.layer.bounds;
                w = b[2].as("px") - b[0].as("px");
                h = b[3].as("px") - b[1].as("px");
                cx = (b[0].as("px") + b[2].as("px")) / 2;
            } catch (eB) {
                continue;
            }
            if (w < 30 || h < 40) {
                continue;
            }
            if (w > cw * 0.42 || h > ch * 0.75) {
                continue;
            }
            if (cx > cw * 0.42) {
                continue;
            }
            var aspect = w / h;
            if (aspect < 0.55 || aspect > 0.9) {
                continue;
            }
            var area = w * h;
            if (area > bestArea) {
                bestArea = area;
                best = item;
            }
        }
        if (best) {
            writeLog(null, "photo card-face " + best.path);
        }
        return best;
    }

    function findPhotoLayer(container, job) {
        var byName = findPhotoByName(container, job);
        if (byName) {
            return byName;
        }
        if (isCardFaceDoc(container, job)) {
            return findPhotoOnCardFace(container, job);
        }
        return null;
    }

    function logDocLayersDeep(doc, tag, depth, prefix) {
        if (depth > 3) {
            return;
        }
        var layers;
        try {
            layers = doc.layers;
        } catch (e) {
            return;
        }
        if (depth === 0) {
            writeLog(null, tag + " '" + docName(doc) + "' deep");
        }
        var limit = layers.length > 30 ? 30 : layers.length;
        for (var i = 0; i < limit; i++) {
            var layer = layers[i];
            var info = prefix || "";
            try {
                info += layer.name;
            } catch (eN) {
                info += "?";
            }
            try {
                info += " " + layer.typename;
            } catch (eT) {}
            try {
                info += " kind=" + layer.kind;
            } catch (eK) {}
            if (isSmartObject(layer)) {
                info += " SO";
            }
            try {
                info += " vis=" + isVisible(layer);
            } catch (eV) {}
            writeLog(null, "  D " + info);
            try {
                if (layer.typename === "LayerSet") {
                    logDocLayersDeep(layer, tag, depth + 1, (prefix || "") + layer.name + "/");
                }
            } catch (eSet) {}
        }
    }

    function setTextViaAM(layer, text) {
        if (!selectLayer(layer)) {
            return false;
        }
        var value = String(text);
        try {
            var ref = new ActionReference();
            ref.putEnumerated(
                stringIDToTypeID("textLayer"),
                stringIDToTypeID("ordinal"),
                stringIDToTypeID("targetEnum")
            );
            var current = executeActionGet(ref);
            if (!current.hasKey(stringIDToTypeID("textKey"))) {
                return false;
            }
            var textKey = current.getObjectValue(stringIDToTypeID("textKey"));
            textKey.putString(charIDToTypeID("Txt "), value);
            try {
                if (textKey.hasKey(stringIDToTypeID("textStyleRange"))) {
                    var oldList = textKey.getList(stringIDToTypeID("textStyleRange"));
                    if (oldList.count > 0) {
                        var first = oldList.getObjectValue(0);
                        first.putInteger(stringIDToTypeID("from"), 0);
                        first.putInteger(stringIDToTypeID("to"), value.length);
                        var newList = new ActionList();
                        newList.putObject(stringIDToTypeID("textStyleRange"), first);
                        textKey.putList(stringIDToTypeID("textStyleRange"), newList);
                    }
                }
            } catch (eRange) {}
            var desc = new ActionDescriptor();
            desc.putReference(charIDToTypeID("null"), ref);
            desc.putObject(charIDToTypeID("T   "), stringIDToTypeID("textLayer"), textKey);
            executeAction(charIDToTypeID("setd"), desc, DialogModes.NO);
            return true;
        } catch (e) {
            writeLog(null, "setText AM preserve: " + e);
            return false;
        }
    }

    function setTextPreserveStyle(layer, text, visible) {
        if (visible === false) {
            try {
                layer.visible = false;
            } catch (eHide) {}
            return;
        }
        if (text === null || text === undefined || text === "") {
            return;
        }
        try {
            layer.visible = true;
        } catch (eShow) {}
        var newText = String(text);
        try {
            layer.textItem.contents = newText;
            return;
        } catch (eDom) {}
        if (!setTextViaAM(layer, newText)) {
            throw new Error("setText failed on '" + layer.name + "'");
        }
    }

    function setTextSafe(layer, text, visible) {
        try {
            setTextPreserveStyle(layer, text, visible);
            return true;
        } catch (e) {
            writeLog(null, "setText skip '" + layer.name + "': " + e);
            return false;
        }
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
                if (mapHas(byName, layer.name)) {
                    setLayerFont(layer, mapGet(byName, layer.name), job);
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

    function logDocLayers(doc, tag) {
        try {
            var layers = doc.layers;
            writeLog(null, tag + " '" + docName(doc) + "' count=" + layers.length);
            var n = layers.length > 40 ? 40 : layers.length;
            for (var i = 0; i < n; i++) {
                var layer = layers[i];
                var info = "";
                try {
                    info += layer.name;
                } catch (eN) {
                    info += "?";
                }
                try {
                    info += " " + layer.typename;
                } catch (eT) {}
                try {
                    info += " kind=" + layer.kind;
                } catch (eK) {
                    info += " kind=?";
                }
                if (isSmartObject(layer)) {
                    info += " SO";
                }
                writeLog(null, "  L " + info);
            }
        } catch (e) {
            writeLog(null, tag + " list failed: " + e);
        }
    }

    function lookupReplacement(byName, replacements, layer) {
        var nm = "";
        try {
            nm = String(layer.name).replace(/^\s+|\s+$/g, "");
        } catch (eN) {}
        if (nm && mapHas(byName, nm)) {
            return mapGet(byName, nm);
        }
        if (replacements) {
            for (var i = 0; i < replacements.length; i++) {
                var row = replacements[i];
                if (row && nm && row.name === nm) {
                    return row.value;
                }
            }
        }
        return null;
    }

    function updateNamedTextLayers(doc, byName, replacements) {
        var layers = [];
        collectTextLayers(doc, layers, false, "Text");
        var hit = 0;
        for (var i = 0; i < layers.length; i++) {
            var layer = layers[i];
            var value = lookupReplacement(byName || {}, replacements, layer);
            if (value === null || value === undefined || value === "") {
                continue;
            }
            var nm = "";
            try {
                nm = String(layer.name);
            } catch (eN) {
                nm = "?";
            }
            if (setTextSafe(layer, value, true)) {
                hit++;
                writeLog(null, "set [" + nm + "] => " + value);
            }
        }
        writeLog(null, "text-by-name in '" + docName(doc) + "': layers=" + layers.length + " updated=" + hit);
        return hit;
    }

    function groupHasDirectSmartObject(group) {
        try {
            var layers = group.layers;
            for (var i = 0; i < layers.length; i++) {
                if (layers[i].typename === "ArtLayer" && isSmartObject(layers[i])) {
                    return true;
                }
            }
        } catch (e) {}
        return false;
    }

    function groupHasDirectTextLayers(group) {
        var textLayers = [];
        collectTextLayers(group, textLayers, true);
        return textLayers.length > 0;
    }

    function hideGroupsNamed(doc, name) {
        var groups = [];
        findGroupsNamed(doc, name, groups);
        var hidden = 0;
        for (var i = 0; i < groups.length; i++) {
            var g = groups[i];
            if (name === "Text" && groupHasDirectSmartObject(g)) {
                try {
                    g.visible = true;
                } catch (eKeep) {}
                writeLog(null, "keep group 'Text' (front SO) in '" + docName(doc) + "'");
                continue;
            }
            if (name === "Text" && !groupHasDirectTextLayers(g)) {
                try {
                    g.visible = true;
                } catch (eKeep2) {}
                continue;
            }
            try {
                g.visible = false;
                hidden++;
            } catch (e) {}
        }
        if (hidden) {
            writeLog(
                null,
                "hide group '" + name + "' count=" + hidden + " in '" + docName(doc) + "'"
            );
        }
        return hidden;
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
            if (!mapHas(catVis, layerName)) {
                continue;
            }
            var layer = findLayerByName(doc, layerName);
            if (!layer) {
                continue;
            }
            if (catVis[layerName]) {
                layer.visible = true;
                if (byName && mapHas(byName, layerName)) {
                    setTextSafe(layer, mapGet(byName, layerName), true);
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

    function openFileResilient(file) {
        var existing = findOpenDoc(file.fsName);
        if (existing) {
            try {
                app.activeDocument = existing;
            } catch (eAct) {}
            writeLog(null, "reused open " + docName(existing));
            return docName(existing);
        }
        var before = app.documents.length;
        try {
            app.open(file);
        } catch (eOpen) {
            if (app.documents.length <= before && !findOpenDoc(file.fsName)) {
                throw eOpen;
            }
            writeLog(null, "open despite: " + eOpen);
        }
        existing = findOpenDoc(file.fsName);
        if (existing) {
            try {
                app.activeDocument = existing;
            } catch (eAct2) {}
            return docName(existing);
        }
        return docName(app.activeDocument);
    }

    function closeCachedTemplate(job) {
        if (!job || !job.template) {
            return;
        }
        var existing = findOpenDoc(job.template);
        if (!existing) {
            return;
        }
        var n = docName(existing);
        writeLog(null, "closing cached template before blank: " + n);
        closeByName(n);
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

    function keepDocNames(extra) {
        var keep = [];
        if (gWorkName) {
            keep.push(gWorkName);
        }
        if (gTemplateName) {
            keep.push(gTemplateName);
        }
        if (extra) {
            for (var i = 0; i < extra.length; i++) {
                if (extra[i]) {
                    keep.push(extra[i]);
                }
            }
        }
        return keep;
    }

    function closeOrphans(extraKeep) {
        var keep = keepDocNames(extraKeep);
        var names = [];
        var i;
        for (i = 0; i < app.documents.length; i++) {
            try {
                names.push(String(app.documents[i].name));
            } catch (e) {}
        }
        for (i = 0; i < names.length; i++) {
            var skip = false;
            for (var k = 0; k < keep.length; k++) {
                if (names[i] === keep[k]) {
                    skip = true;
                    break;
                }
            }
            if (!skip) {
                writeLog(null, "closing orphan " + names[i]);
                closeByName(names[i]);
            }
        }
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
            var dup = templateDoc.duplicate(workName, false);
            workName = docName(dup) || docName(app.activeDocument) || workName;
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
            return 0;
        }
        var prefix = job.scene.background_prefix || "Вариант ";
        var count = job.scene.background_count || 10;
        var found = 0;
        for (var i = 1; i <= count; i++) {
            var layerName = prefix + i;
            forEachLayerByName(doc, layerName, function (layer) {
                found++;
                setLayerVisible(layer, i === job.background);
            });
        }
        writeLog(null, "background #" + job.background + " in '" + docName(doc) + "' variants=" + found);
        return found;
    }

    function applyPortraitIfNeeded(doc, job) {
        if (job._portraitDone) {
            return true;
        }
        if (!job.portrait_path) {
            return false;
        }
        if (!isCardFaceDoc(doc, job)) {
            writeLog(null, "portrait skip scene doc '" + docName(doc) + "'");
            return false;
        }
        var found = findPhotoLayer(doc, job);
        if (!found) {
            writeLog(null, "Photo layer not in card '" + docName(doc) + "'");
            return false;
        }
        writeLog(null, "portrait -> " + found.path + " in '" + docName(doc) + "'");
        if (replacePortrait(found.layer, job.portrait_path, job)) {
            job._portraitDone = true;
            return true;
        }
        return false;
    }

    function forEachLayerDeep(container, fn) {
        var layers;
        try {
            layers = container.layers;
        } catch (e) {
            return;
        }
        for (var i = 0; i < layers.length; i++) {
            fn(layers[i]);
            try {
                if (layers[i].typename === "LayerSet") {
                    forEachLayerDeep(layers[i], fn);
                }
            } catch (eSet) {}
        }
    }

    function toggleNamedLayers(doc, name, visible) {
        var n = 0;
        if (!name) {
            return 0;
        }
        forEachLayerByName(doc, name, function (layer) {
            try {
                setLayerVisible(layer, visible);
                n++;
            } catch (e) {}
        });
        if (n === 0) {
            var key = layerNameKey(name);
            forEachLayerDeep(doc, function (layer) {
                var ln = "";
                try {
                    ln = String(layer.name);
                } catch (eN) {
                    return;
                }
                if (layerNameKey(ln) === key) {
                    try {
                        setLayerVisible(layer, visible);
                        n++;
                    } catch (e2) {}
                }
            });
        }
        return n;
    }

    function handChromeNames(job) {
        var scene = (job && job.scene) || {};
        var names = [];
        if (scene.hand_smart_object) {
            names.push(scene.hand_smart_object);
        }
        var extra = scene.skip_smart_objects || [];
        var i;
        for (i = 0; i < extra.length; i++) {
            names.push(extra[i]);
        }
        return names;
    }

    function hideHandChromeOnly(doc, job) {
        var n = 0;
        var names = handChromeNames(job);
        var i;
        for (i = 0; i < names.length; i++) {
            n += toggleNamedLayers(doc, names[i], false);
        }
        return n;
    }

    function showHandChrome(doc, job) {
        var n = 0;
        var names = handChromeNames(job);
        var i;
        for (i = 0; i < names.length; i++) {
            n += toggleNamedLayers(doc, names[i], true);
        }
        return n;
    }

    function showCardStack(doc, job) {
        var scene = (job && job.scene) || {};
        var n = 0;
        n += toggleNamedLayers(doc, scene.hand_group, true);
        var cards = scene.card_smart_objects || [];
        var i;
        for (i = 0; i < cards.length; i++) {
            n += toggleNamedLayers(doc, cards[i], true);
        }
        var wraps = scene.card_wrappers || [];
        for (i = 0; i < wraps.length; i++) {
            n += toggleNamedLayers(doc, wraps[i], true);
        }
        return n;
    }

    function hidePlateByKey(doc, name) {
        var n = 0;
        var key = layerNameKey(name);
        if (!key) {
            return 0;
        }
        forEachLayerDeep(doc, function (layer) {
            var ln = "";
            try {
                ln = String(layer.name);
            } catch (eN) {
                return;
            }
            if (layerNameKey(ln) === key) {
                try {
                    layer.visible = false;
                    n++;
                } catch (eV) {}
            }
        });
        return n;
    }

    function revealLayerChain(layer) {
        var cur = layer;
        for (var i = 0; i < 10 && cur; i++) {
            try {
                cur.visible = true;
            } catch (eV) {}
            try {
                cur.grouped = false;
            } catch (eG) {}
            try {
                if (cur.typename === "ArtLayer") {
                    cur.layerMaskDisabled = true;
                }
            } catch (eM) {}
            try {
                if (cur.typename === "Document") {
                    break;
                }
                cur = cur.parent;
            } catch (eP) {
                break;
            }
        }
    }

    function moveLayerOrder(layer, where) {
        if (!selectLayer(layer)) {
            return false;
        }
        try {
            var desc = new ActionDescriptor();
            var ref = new ActionReference();
            ref.putEnumerated(charIDToTypeID("Lyr "), charIDToTypeID("Ordn"), charIDToTypeID("Trgt"));
            desc.putReference(charIDToTypeID("null"), ref);
            var ref2 = new ActionReference();
            ref2.putEnumerated(charIDToTypeID("Lyr "), charIDToTypeID("Ordn"), charIDToTypeID(where));
            desc.putReference(charIDToTypeID("T   "), ref2);
            executeAction(charIDToTypeID("move"), desc, DialogModes.NO);
            return true;
        } catch (e) {
            writeLog(null, "move layer " + where + ": " + e);
            return false;
        }
    }

    function liftNamedLayers(doc, name) {
        var n = 0;
        if (!name) {
            return 0;
        }
        forEachLayerByName(doc, name, function (layer) {
            revealLayerChain(layer);
            if (moveLayerOrder(layer, "Frnt")) {
                n++;
            }
        });
        return n;
    }

    function applyMockupVariant(doc, job) {
        if (!job.mockup_variant || !job.scene) {
            return;
        }
        var orig = job.scene.original_layer;
        var hand = job.scene.hand_group;
        if (job.mockup_variant === "hand") {
            var hidPlate = hidePlateByKey(doc, orig);
            var shownCard = showCardStack(doc, job);
            var shownHand = showHandChrome(doc, job);
            writeLog(
                null,
                "variant hand hidePlate=" + hidPlate + " showCard=" + shownCard +
                    " showHand=" + shownHand + " in '" + docName(doc) + "'"
            );
            return;
        }
        if (job.mockup_variant === "original") {
            // «Оригинал» = стена. Карточка и рука лежат в «Рука+док» — их нельзя гасить.
            var shownWall = toggleNamedLayers(doc, orig, true);
            var shownCard = showCardStack(doc, job);
            var shownHand = showHandChrome(doc, job);
            var hidStudio = 0;
            if (job.scene.background_smart_object) {
                hidStudio = toggleNamedLayers(doc, job.scene.background_smart_object, false);
            }
            writeLog(
                null,
                "variant original showWall=" + shownWall + " showCard=" + shownCard +
                    " showHand=" + shownHand + " hideStudio=" + hidStudio +
                    " in '" + docName(doc) + "'"
            );
        }
    }

    function placeCardOnScene(doc, cardFile) {
        var file = (cardFile instanceof File) ? cardFile : new File(cardFile);
        if (!file.exists) {
            writeLog(null, "place card missing: " + file.fsName);
            return false;
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
                writeLog(null, "place card failed: " + ePlc2);
                return false;
            }
        }
        try {
            var layer = doc.activeLayer;
            try {
                layer.grouped = false;
            } catch (eG) {}
            var b = layer.bounds;
            var w = b[2].as("px") - b[0].as("px");
            var cw = doc.width.as("px");
            var ch = doc.height.as("px");
            if (w > 1) {
                layer.resize((cw * 0.36 / w) * 100, (cw * 0.36 / w) * 100, AnchorPosition.MIDDLECENTER);
            }
            b = layer.bounds;
            var cx = (b[0].as("px") + b[2].as("px")) / 2;
            var cy = (b[1].as("px") + b[3].as("px")) / 2;
            layer.translate(cw * 0.5 - cx, ch * 0.48 - cy);
            writeLog(null, "placed opaque card on scene");
            return true;
        } catch (eSc) {
            writeLog(null, "scale placed card: " + eSc);
            return true;
        }
    }

    function composeOriginalScene(workName, job) {
        if (!job || job.mockup_variant !== "original") {
            return;
        }
        if (!activateByName(workName)) {
            writeLog(null, "compose original: work doc lost");
            return;
        }
        var hidG = toggleNamedLayers(app.activeDocument, job.scene.hand_group, false);
        var hidH = hideHandChromeOnly(app.activeDocument, job);
        var hidP = hidePlateByKey(app.activeDocument, job.scene.original_layer);
        writeLog(
            null,
            "compose original hideGroup=" + hidG + " hideHand=" + hidH + " hidePlate=" + hidP
        );
        var card = renderBlankCard(job);
        if (!card) {
            writeLog(null, "compose original: blank card failed");
            return;
        }
        if (!activateByName(workName)) {
            writeLog(null, "compose original: work doc lost after blank");
            return;
        }
        placeCardOnScene(app.activeDocument, card);
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

    function convertLayerToSmartObject(layer) {
        if (!selectLayer(layer)) {
            return false;
        }
        if (isSmartObject(layer)) {
            return true;
        }
        try {
            executeAction(stringIDToTypeID("newPlacedLayer"), new ActionDescriptor(), DialogModes.NO);
            return true;
        } catch (e) {
            writeLog(null, "convert SO failed: " + e);
            return false;
        }
    }

    function replacePortrait(layer, imagePath, job) {
        var file = new File(imagePath);
        if (!file.exists) {
            writeLog(null, "portrait file missing: " + imagePath);
            return false;
        }
        if (isProtectedSceneLayer(layer, job)) {
            writeLog(null, "portrait refuse protected layer: " + layer.name);
            return false;
        }
        if (!selectLayer(layer)) {
            writeLog(null, "portrait layer not selectable");
            return false;
        }
        if (!isSmartObject(layer) && !convertLayerToSmartObject(layer)) {
            return false;
        }
        try {
            layer = app.activeDocument.activeLayer;
        } catch (eAct) {}
        var placed = false;
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
            placed = true;
        }, true);
        if (placed) {
            writeLog(null, "portrait placed via edit contents");
            return true;
        }
        if (replaceSmartObjectContents(file)) {
            writeLog(null, "portrait replaced contents");
            return true;
        }
        return false;
    }

    function selectLayer(layer) {
        try {
            app.activeDocument.activeLayer = layer;
            return true;
        } catch (eDom) {}
        try {
            var ref = new ActionReference();
            ref.putIdentifier(charIDToTypeID("Lyr "), layer.id);
            var desc = new ActionDescriptor();
            desc.putReference(charIDToTypeID("null"), ref);
            desc.putBoolean(charIDToTypeID("MkVs"), false);
            executeAction(charIDToTypeID("slct"), desc, DialogModes.NO);
            return true;
        } catch (eAm) {
            return false;
        }
    }

    function smartObjectOpened(parentName, beforeCount) {
        try {
            if (app.documents.length > beforeCount) {
                return true;
            }
            var n = docName(app.activeDocument);
            return !!(n && n !== parentName);
        } catch (e) {
            return app.documents.length > beforeCount;
        }
    }

    function tempSoFile(layerName, ext) {
        var safe = String(layerName || "so").replace(/[^a-zA-Z0-9_-]/g, "_");
        if (safe.length > 40) {
            safe = safe.substring(0, 40);
        }
        return new File(Folder.temp.fsName + "/vu_so_" + safe + "_" + (new Date().getTime()) + (ext || ".psb"));
    }

    function executePathAction(ids, file) {
        for (var i = 0; i < ids.length; i++) {
            try {
                var desc = new ActionDescriptor();
                desc.putPath(charIDToTypeID("null"), file);
                executeAction(stringIDToTypeID(ids[i]), desc, DialogModes.NO);
                return true;
            } catch (e) {}
        }
        return false;
    }

    function exportSmartObjectContents(destFile) {
        executePathAction(
            ["placedLayerExportContents", "exportContents", "exportSmartObject"],
            destFile
        );
        return destFile.exists && destFile.length > 0;
    }

    function replaceSmartObjectContents(srcFile) {
        return executePathAction(
            ["placedLayerReplaceContents", "placedLayerRelinkToFile", "placedLayerRelinkToFileWithParams"],
            srcFile
        );
    }

    function saveDocTo(file) {
        try {
            app.activeDocument.save();
            if (file.exists && file.length > 0) {
                return true;
            }
        } catch (e1) {}
        try {
            var opts = new PhotoshopSaveOptions();
            opts.layers = true;
            try {
                opts.maximizeCompatibility = true;
            } catch (eMc) {}
            app.activeDocument.saveAs(file, opts, false, Extension.LOWERCASE);
            return file.exists;
        } catch (e2) {
            try {
                saveMasterAM(file, /\.psb$/i.test(file.name));
                return file.exists;
            } catch (e3) {
                return false;
            }
        }
    }

    function editSmartObjectViaExport(layer, fn) {
        var parentName = docName(app.activeDocument);
        var layerName = "";
        try {
            layerName = String(layer.name);
        } catch (eN) {}
        if (!selectLayer(layer)) {
            writeLog(null, "SO export: not selectable " + layerName);
            return false;
        }
        var out = tempSoFile(layerName, ".psb");
        if (!exportSmartObjectContents(out)) {
            out = tempSoFile(layerName, ".psd");
            if (!exportSmartObjectContents(out)) {
                writeLog(null, "SO export failed: " + layerName);
                return false;
            }
        }
        writeLog(null, "SO exported " + layerName + " -> " + out.fsName + " (" + out.length + ")");
        var openedName = "";
        try {
            app.open(out);
            openedName = docName(app.activeDocument);
            fn(app.activeDocument);
            if (!saveDocTo(out)) {
                throw new Error("could not save exported SO");
            }
            closeByName(openedName);
            openedName = "";
            if (!activateByName(parentName) || !selectLayer(layer)) {
                throw new Error("lost parent after SO export edit");
            }
            if (!replaceSmartObjectContents(out)) {
                throw new Error("placedLayerReplaceContents failed");
            }
            writeLog(null, "SO replaced: " + layerName);
            return true;
        } catch (e) {
            writeLog(null, "SO export-edit failed (" + layerName + "): " + e);
            if (openedName) {
                closeByName(openedName);
            }
            activateByName(parentName);
            return false;
        } finally {
            try {
                out.remove();
            } catch (eRm) {}
        }
    }

    function openSmartObject() {
        // PS 2026 often throws Error 54 AFTER the SO document is already open.
        var parentName = docName(app.activeDocument);
        var before = app.documents.length;
        var tries = [
            function () {
                executeAction(stringIDToTypeID("placedLayerEditContents"), undefined, DialogModes.NO);
            },
            function () {
                executeAction(stringIDToTypeID("placedLayerEditContents"), new ActionDescriptor(), DialogModes.NO);
            },
            function () {
                var desc = new ActionDescriptor();
                var ref = new ActionReference();
                ref.putEnumerated(charIDToTypeID("Lyr "), charIDToTypeID("Ordn"), charIDToTypeID("Trgt"));
                desc.putReference(charIDToTypeID("null"), ref);
                executeAction(stringIDToTypeID("placedLayerEditContents"), desc, DialogModes.NO);
            },
            function () {
                app.runMenuItem(stringIDToTypeID("placedLayerEditContents"));
            }
        ];
        for (var i = 0; i < tries.length; i++) {
            try {
                tries[i]();
            } catch (eTry) {
                if (smartObjectOpened(parentName, before)) {
                    writeLog(null, "smart object opened despite: " + eTry);
                    return true;
                }
                continue;
            }
            if (smartObjectOpened(parentName, before)) {
                return true;
            }
        }
        return false;
    }

    function editSmartObject(layer, fn, allowExport) {
        if (allowExport !== false) {
            allowExport = true;
        }
        var parentName = docName(app.activeDocument);
        var layerName = "";
        try {
            layerName = String(layer.name);
        } catch (eName) {}

        if (!selectLayer(layer)) {
            writeLog(null, "smart object not selectable: " + layerName);
            return;
        }

        var wasLocked = false;
        try {
            if (layer.allLocked) {
                layer.allLocked = false;
                wasLocked = true;
            }
        } catch (eLock) {}

        var innerName = "";
        var opened = false;
        try {
            if (!openSmartObject()) {
                writeLog(null, "Edit Contents unavailable, export/replace: " + layerName);
                closeOrphans([parentName]);
                activateByName(parentName);
                if (allowExport && editSmartObjectViaExport(layer, fn)) {
                    return;
                }
                writeLog(null, "smart object not editable: " + layerName);
                return;
            }
            innerName = docName(app.activeDocument);
            if (!innerName || innerName === parentName) {
                writeLog(null, "smart object did not open, export/replace: " + layerName);
                if (allowExport && editSmartObjectViaExport(layer, fn)) {
                    return;
                }
                writeLog(null, "smart object did not open: " + layerName);
                return;
            }
            opened = true;
            fn(app.activeDocument);
        } catch (eEdit) {
            writeLog(null, "smart object failed (" + layerName + "): " + eEdit);
            if (!opened && allowExport) {
                activateByName(parentName);
                editSmartObjectViaExport(layer, fn);
            }
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
            if (wasLocked) {
                try {
                    layer.allLocked = true;
                } catch (eRelock) {}
            }
        }
    }

    function isSmartObject(layer) {
        try {
            return layer.kind === LayerKind.SMARTOBJECT;
        } catch (e) {
            return false;
        }
    }

    function isVisible(layer) {
        try {
            return layer.visible !== false;
        } catch (e) {
            return true;
        }
    }

    function walkLayers(layers, job, depth) {
        if (depth > 6) {
            return;
        }
        for (var i = 0; i < layers.length; i++) {
            var layer = layers[i];
            if (layer.typename === "LayerSet") {
                try {
                    if (String(layer.name) === "Text" && groupHasDirectSmartObject(layer)) {
                        layer.visible = true;
                    }
                } catch (eTxtGrp) {}
                walkLayers(layer.layers, job, depth);
            } else if (layer.typename === "ArtLayer" && isSmartObject(layer)) {
                var scene = job.scene || {};
                var isBg = scene.background_smart_object && layer.name === scene.background_smart_object;
                var isPhoto = isPhotoName(layer.name, job);
                var isOrig = scene.original_layer && layer.name === scene.original_layer;
                var isHand = scene.hand_group && layer.name === scene.hand_group;
                var isCard = isCardSmartObject(layer, job);
                if (isHand) {
                    continue;
                }
                if (isOrig) {
                    continue;
                }
                if (isCard) {
                    try {
                        layer.visible = true;
                    } catch (eCardVis) {}
                }
                if (!isVisible(layer) && !isBg && !isPhoto && !isCard) {
                    continue;
                }
                try {
                    if (isPhoto) {
                        if (isProtectedSceneLayer(layer, job)) {
                            writeLog(null, "portrait refuse protected SO: " + layer.name);
                        } else if (job.portrait_path && !job._portraitDone) {
                            writeLog(null, "portrait walk -> " + layer.name);
                            if (replacePortrait(layer, job.portrait_path, job)) {
                                job._portraitDone = true;
                            }
                        }
                    } else if (isBg) {
                        if (job.mockup_variant === "original") {
                            try {
                                layer.visible = false;
                            } catch (eHidBg) {}
                            writeLog(null, "studio bg hidden for original");
                        } else {
                            try {
                                layer.visible = true;
                            } catch (eVis) {}
                            editSmartObject(layer, function (innerDoc) {
                                applyBackground(innerDoc, job);
                            });
                        }
                    } else if (isCard) {
                        var cardName = "";
                        try {
                            cardName = String(layer.name);
                        } catch (eCn) {}
                        if (job._textSODone && (cardName === "Text" || cardName === "text" || cardName === "TEXT")) {
                            writeLog(null, "skip Text SO already filled");
                        } else {
                            writeLog(null, "edit card SO in place: " + layer.name);
                            if (cardName === "Text" || cardName === "text" || cardName === "TEXT") {
                                job._textSODone = true;
                            }
                            editSmartObject(layer, function (innerDoc) {
                                applyTextMaps(
                                    innerDoc,
                                    job.layers_by_name || {},
                                    job.text_group_values,
                                    job.text_group_visibility,
                                    job.category_visibility,
                                    job,
                                    job.text_replacements
                                );
                                walkLayers(innerDoc.layers, job, depth + 1);
                            }, true);
                            job._cardEdited = (job._cardEdited || 0) + 1;
                        }
                    } else if (isWrapperSmartObject(layer, job)) {
                        writeLog(null, "enter wrapper SO: " + layer.name);
                        editSmartObject(layer, function (innerDoc) {
                            applyJob(innerDoc, job, depth + 1);
                        }, false);
                    } else if (job.blank_template) {
                        writeLog(null, "skip chrome SO: " + layer.name);
                    } else {
                        try {
                            layer.visible = true;
                        } catch (eVis2) {}
                        editSmartObject(layer, function (innerDoc) {
                            applyJob(innerDoc, job, depth + 1);
                        });
                    }
                } catch (eSO) {
                    writeLog(null, "walkLayers skip " + layer.name + ": " + eSO);
                    closeOrphans([docName(app.activeDocument)]);
                }
            }
        }
    }

    function applyTextMaps(doc, byName, textVals, textVis, catVis, job, replacements) {
        try {
            app.activeDocument = doc;
        } catch (eAct) {}
        logDocLayers(doc, "card layers");
        if (job && job.portrait_path && !job._portraitDone) {
            logDocLayersDeep(doc, "card deep", 0, "");
            applyPortraitIfNeeded(doc, job);
        }
        var hits = 0;
        try {
            hits = updateNamedTextLayers(doc, byName || {}, replacements);
        } catch (eName) {
            writeLog(null, "updateNamedTextLayers: " + eName);
        }
        try {
            applyCategoryVisibility(doc, catVis || null, byName || {});
        } catch (eCat) {
            writeLog(null, "applyCategoryVisibility: " + eCat);
        }
        try {
            updateTextGroupByIndex(doc, textVals || [], textVis || null);
        } catch (eGrp) {
            writeLog(null, "updateTextGroupByIndex: " + eGrp);
        }
        try {
            hideGroupsNamed(doc, "Text");
        } catch (eHide) {}
        if (hits < 1 && job && !job._textSODone) {
            hits += enterNestedTextSmartObject(doc, byName, textVals, textVis, catVis, job, replacements);
        }
        writeLog(null, "applyTextMaps '" + docName(doc) + "' namedHits=" + hits);
        return hits;
    }

    function enterNestedTextSmartObject(doc, byName, textVals, textVis, catVis, job, replacements) {
        var hits = 0;
        function walk(layers) {
            for (var i = 0; i < layers.length; i++) {
                var layer = layers[i];
                var typename = "";
                try {
                    typename = layer.typename;
                } catch (eT) {
                    continue;
                }
                if (typename === "LayerSet") {
                    walk(layer.layers);
                } else if (typename === "ArtLayer" && isSmartObject(layer)) {
                    var nm = "";
                    try {
                        nm = String(layer.name);
                    } catch (eN) {}
                    if (nm !== "Text" && nm !== "text" && nm !== "TEXT") {
                        continue;
                    }
                    try {
                        layer.visible = true;
                    } catch (eVis) {}
                    writeLog(null, "enter nested Text SO in '" + docName(doc) + "'");
                    job._textSODone = true;
                    editSmartObject(layer, function (innerDoc) {
                        hits += applyTextMaps(
                            innerDoc,
                            byName,
                            textVals,
                            textVis,
                            catVis,
                            job,
                            replacements
                        );
                    }, true);
                }
            }
        }
        try {
            walk(doc.layers);
        } catch (eW) {
            writeLog(null, "nested Text SO: " + eW);
        }
        return hits;
    }

    function applyTextMapsDeep(doc, byName, textVals, textVis, catVis, job, replacements, depth) {
        if (depth > 5) {
            return 0;
        }
        var hits = applyTextMaps(doc, byName, textVals, textVis, catVis, job, replacements);
        function walk(layers) {
            for (var i = 0; i < layers.length; i++) {
                var layer = layers[i];
                var typename = "";
                try {
                    typename = layer.typename;
                } catch (eT) {
                    continue;
                }
                if (typename === "LayerSet") {
                    walk(layer.layers);
                } else if (typename === "ArtLayer" && isSmartObject(layer)) {
                    writeLog(null, "blank inner SO: " + layer.name);
                    editSmartObject(layer, function (innerDoc) {
                        hits += applyTextMapsDeep(
                            innerDoc,
                            byName,
                            textVals,
                            textVis,
                            catVis,
                            job,
                            replacements,
                            depth + 1
                        );
                    }, true);
                }
            }
        }
        try {
            walk(doc.layers);
        } catch (eW) {
            writeLog(null, "deep walk: " + eW);
        }
        return hits;
    }

    function nameInList(n, list) {
        if (!list) {
            return false;
        }
        for (var i = 0; i < list.length; i++) {
            if (n === list[i]) {
                return true;
            }
        }
        return false;
    }

    function isWrapperSmartObject(layer, job) {
        if (isCardSmartObject(layer, job)) {
            return false;
        }
        var scene = job.scene || {};
        var n = "";
        try {
            n = String(layer.name);
        } catch (e) {
            return true;
        }
        if (scene.photo_smart_object && n === scene.photo_smart_object) {
            return false;
        }
        if (scene.background_smart_object && n === scene.background_smart_object) {
            return false;
        }
        if (scene.original_layer && n === scene.original_layer) {
            return false;
        }
        if (scene.hand_group && n === scene.hand_group) {
            return false;
        }
        if (nameInList(n, scene.skip_smart_objects || job.skip_smart_objects)) {
            return false;
        }
        return nameInList(n, scene.card_wrappers || job.card_wrappers);
    }

    function isCardSmartObject(layer, job) {
        var scene = job.scene || {};
        var n = "";
        try {
            n = String(layer.name);
        } catch (e) {
            return false;
        }
        if (scene.photo_smart_object && n === scene.photo_smart_object) {
            return false;
        }
        if (scene.background_smart_object && n === scene.background_smart_object) {
            return false;
        }
        if (nameInList(n, scene.card_smart_objects) || nameInList(n, job.card_smart_objects)) {
            return true;
        }
        if (n === "Text" || n === "text" || n === "TEXT" || n === "Front" || n === "front") {
            return true;
        }
        if (/^front$|^text$|card|licence|license/i.test(n)) {
            return true;
        }
        return false;
    }

    function logSmartObjects(container, prefix) {
        var layers = container.layers;
        for (var i = 0; i < layers.length; i++) {
            var layer = layers[i];
            var path = prefix ? prefix + "/" + layer.name : layer.name;
            if (layer.typename === "LayerSet") {
                logSmartObjects(layer, path);
            } else if (layer.typename === "ArtLayer" && isSmartObject(layer)) {
                writeLog(null, "SO " + path + " vis=" + isVisible(layer));
            }
        }
    }

    function trySaveCopy(file, isPsb) {
        try {
            if (isPsb) {
                saveMasterAM(file, true);
            } else {
                try {
                    saveMasterAM(file, false);
                } catch (eAm) {
                    writeLog(null, "blank save AM psd: " + eAm);
                }
                if (!fileReady(file)) {
                    saveMasterDom(file);
                }
            }
        } catch (e) {
            writeLog(null, "blank save " + (isPsb ? "psb" : "psd") + ": " + e);
        }
        return fileReady(file);
    }

    function saveFlattenedCard(file) {
        var flatName = "_vu_flat_" + (new Date().getTime());
        var actual = "";
        try {
            var dup = app.activeDocument.duplicate(flatName, true);
            actual = docName(dup) || docName(app.activeDocument) || flatName;
            activateByName(actual);
            try {
                app.activeDocument.flatten();
            } catch (eFlat) {}
            try {
                saveMasterDom(file);
            } catch (eDom) {
                writeLog(null, "flatten save: " + eDom);
            }
            return fileReady(file);
        } catch (e) {
            writeLog(null, "flatten card: " + e);
            return false;
        } finally {
            closeByName(actual || flatName);
        }
    }

    function renderBlankCard(job) {
        if (!job.blank_template) {
            return null;
        }
        var src = new File(job.blank_template);
        if (!src.exists) {
            writeLog(null, "blank_template missing: " + job.blank_template);
            return null;
        }
        var stamp = String(job.job_id || "x") + "_" + (new Date().getTime());
        var tmpPsb = new File(Folder.temp.fsName + "/vu_card_" + stamp + ".psb");
        var tmpPsd = new File(Folder.temp.fsName + "/vu_card_" + stamp + ".psd");
        var srcName = "";
        var workName = "";
        try {
            writeLog(null, "opening blank docs=" + app.documents.length);
            srcName = openFileResilient(src);
            workName = srcName;
            writeLog(null, "blank opened '" + srcName + "' docs=" + app.documents.length);
            if (!activateByName(workName)) {
                throw new Error("blank work doc lost");
            }
            var hits = 0;
            try {
                hits = applyTextMapsDeep(
                    app.activeDocument,
                    job.blank_layers_by_name || job.layers_by_name,
                    job.blank_text_group_values || job.text_group_values,
                    job.blank_text_group_visibility || job.text_group_visibility,
                    job.blank_category_visibility || job.category_visibility,
                    job,
                    job.blank_text_replacements || job.text_replacements,
                    0
                );
            } catch (eMap) {
                writeLog(null, "applyTextMaps error: " + eMap);
            }
            if (hits < 1) {
                writeLog(null, "blank card namedHits=0 — will not replace Front with empty card");
                return null;
            }
            if (!activateByName(workName)) {
                throw new Error("blank work doc lost after text");
            }
            var out = null;
            if (trySaveCopy(tmpPsb, true)) {
                out = tmpPsb;
            } else if (trySaveCopy(tmpPsd, false)) {
                out = tmpPsd;
            } else if (activateByName(workName) && saveFlattenedCard(tmpPsd)) {
                out = tmpPsd;
            }
            if (!out) {
                throw new Error("blank card save failed");
            }
            writeLog(null, "blank card " + out.fsName + " bytes=" + fileSize(out) + " hits=" + hits);
            return out;
        } catch (e) {
            writeLog(null, "blank card failed: " + e);
            return null;
        } finally {
            closeByName(srcName);
        }
    }

    function fillCardSmartObjectsInPlace(container, job) {
        var n = 0;
        function walk(layers) {
            for (var i = 0; i < layers.length; i++) {
                var layer = layers[i];
                if (layer.typename === "LayerSet") {
                    walk(layer.layers);
                } else if (layer.typename === "ArtLayer" && isSmartObject(layer)) {
                    if (isCardSmartObject(layer, job)) {
                        writeLog(null, "export-edit card SO: " + layer.name);
                        if (editSmartObjectViaExport(layer, function (innerDoc) {
                            applyTextMaps(
                                innerDoc,
                                job.layers_by_name || {},
                                job.text_group_values,
                                job.text_group_visibility,
                                job.category_visibility,
                                job,
                                job.text_replacements
                            );
                        })) {
                            n++;
                            job._cardEdited = (job._cardEdited || 0) + 1;
                        }
                    } else if (isWrapperSmartObject(layer, job)) {
                        writeLog(null, "export-edit via wrapper: " + layer.name);
                        editSmartObject(layer, function (innerDoc) {
                            n += fillCardSmartObjectsInPlace(innerDoc, job);
                        }, false);
                    }
                }
            }
        }
        walk(container.layers);
        return n;
    }

    function replaceCardSmartObjects(container, cardFile, job) {
        var n = 0;
        function walk(layers) {
            for (var i = 0; i < layers.length; i++) {
                var layer = layers[i];
                if (layer.typename === "LayerSet") {
                    walk(layer.layers);
                } else if (layer.typename === "ArtLayer" && isSmartObject(layer)) {
                    if (isCardSmartObject(layer, job)) {
                        try {
                            layer.visible = true;
                        } catch (eVis) {}
                        if (selectLayer(layer) && replaceSmartObjectContents(cardFile)) {
                            writeLog(null, "replaced card SO: " + layer.name);
                            n++;
                        } else {
                            writeLog(null, "replace card SO failed: " + layer.name);
                        }
                    } else if (isWrapperSmartObject(layer, job)) {
                        writeLog(null, "replace via wrapper: " + layer.name);
                        editSmartObject(layer, function (innerDoc) {
                            n += replaceCardSmartObjects(innerDoc, cardFile, job);
                        }, false);
                    }
                }
            }
        }
        walk(container.layers);
        return n;
    }

    function applyJob(doc, job, depth) {
        try {
            app.activeDocument = doc;
        } catch (eAct) {}
        applyMockupVariant(doc, job);
        if (job.mockup_variant !== "original") {
            applyBackground(doc, job);
        }
        applyPortraitIfNeeded(doc, job);
        var byName = job.layers_by_name || {};
        var hits = updateNamedTextLayers(doc, byName, job.text_replacements);
        applyCategoryVisibility(doc, job.category_visibility || null, byName);
        updateTextGroupByIndex(doc, job.text_group_values || [], job.text_group_visibility || null);
        hideGroupsNamed(doc, "Text");
        walkLayers(doc.layers, job, depth || 0);
        writeLog(null, "applyJob depth=" + (depth || 0) + " doc='" + docName(doc) + "' namedHits=" + hits);
    }

    function saveMasterAM(file, isPsb) {
        var desc = new ActionDescriptor();
        var fmt = new ActionDescriptor();
        try {
            fmt.putBoolean(stringIDToTypeID("maximizeCompatibility"), true);
        } catch (eMc) {}
        var typeId = isPsb
            ? stringIDToTypeID("largeDocumentFormat")
            : stringIDToTypeID("photoshop35Format");
        desc.putObject(charIDToTypeID("As  "), typeId, fmt);
        desc.putPath(charIDToTypeID("In  "), file);
        desc.putBoolean(charIDToTypeID("Cpy "), true);
        try {
            desc.putBoolean(charIDToTypeID("LwCs"), true);
        } catch (eLc) {}
        executeAction(charIDToTypeID("save"), desc, DialogModes.NO);
    }

    function saveMasterDom(file) {
        var opts = new PhotoshopSaveOptions();
        opts.layers = true;
        opts.embedColorProfile = true;
        try {
            opts.maximizeCompatibility = true;
        } catch (eMc) {}
        app.activeDocument.saveAs(file, opts, true, Extension.LOWERCASE);
    }

    /**
     * Always saves a copy: the work document keeps its name, so the caller
     * never has to deal with a renamed/stale document handle afterwards.
     * PSB can only be written through Action Manager (no DOM save option).
     */
    function saveMaster(workName, file, isPsb) {
        if (!activateByName(workName)) {
            throw new Error("Work document not found: " + workName);
        }
        var errors = [];
        var attempts = isPsb
            ? [
                  ["psb", function () { saveMasterAM(file, true); }],
                  ["psd-am", function () { saveMasterAM(file, false); }],
                  ["psd-dom", function () { saveMasterDom(file); }]
              ]
            : [
                  ["psd-dom", function () { saveMasterDom(file); }],
                  ["psd-am", function () { saveMasterAM(file, false); }]
              ];

        for (var i = 0; i < attempts.length; i++) {
            try {
                attempts[i][1]();
                if (fileReady(file)) {
                    writeLog(null, "master saved via " + attempts[i][0] + " (" + fileSize(file) + " bytes)");
                    return;
                }
                errors.push(attempts[i][0] + ": no file on disk");
            } catch (e) {
                errors.push(attempts[i][0] + ": " + e);
            }
            if (!activateByName(workName)) {
                break;
            }
        }
        throw new Error("master save failed -> " + errors.join(" | "));
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

    function exportJpeg(workName, file) {
        if (!activateByName(workName)) {
            throw new Error("Work document not found for JPEG: " + workName);
        }
        var opts = jpegOptions();
        var errors = [];

        try {
            app.activeDocument.saveAs(file, opts, true, Extension.LOWERCASE);
            if (fileReady(file)) {
                writeLog(null, "jpeg saved (" + fileSize(file) + " bytes)");
                return;
            }
            errors.push("as-copy: no file on disk");
        } catch (eJpg) {
            errors.push("as-copy: " + eJpg);
        }

        // JPEG rejects layered/16-bit/non-RGB documents: export a flat duplicate.
        var dupName = "_vu_jpg_" + (new Date().getTime());
        var actual = "";
        try {
            if (!activateByName(workName)) {
                throw new Error("work document lost before JPEG flatten");
            }
            var dup = app.activeDocument.duplicate(dupName, true);
            actual = docName(dup) || docName(app.activeDocument) || dupName;
            activateByName(actual);
            try {
                app.activeDocument.flatten();
            } catch (eFlat) {}
            try {
                if (app.activeDocument.bitsPerChannel !== BitsPerChannelType.EIGHT) {
                    app.activeDocument.bitsPerChannel = BitsPerChannelType.EIGHT;
                }
            } catch (eBits) {}
            try {
                if (app.activeDocument.mode !== DocumentMode.RGB) {
                    app.activeDocument.changeMode(ChangeMode.RGB);
                }
            } catch (eMode) {}
            app.activeDocument.saveAs(file, opts, true, Extension.LOWERCASE);
        } catch (eDup) {
            errors.push("flatten: " + eDup);
        } finally {
            closeByName(actual || dupName);
            if (actual && actual !== dupName) {
                closeByName(dupName);
            }
            activateByName(workName);
        }

        if (fileReady(file)) {
            writeLog(null, "jpeg saved via flatten (" + fileSize(file) + " bytes)");
            return;
        }
        throw new Error("jpeg export failed -> " + errors.join(" | "));
    }

    function fresh(f) {
        // File objects cache exists/length; re-read the path before checking.
        try {
            return new File(f.fsName);
        } catch (e) {
            return f;
        }
    }

    function fileSize(f) {
        try {
            return fresh(f).length;
        } catch (e) {
            return -1;
        }
    }

    function fileReady(f) {
        var probe = fresh(f);
        try {
            return probe.exists && probe.length > 0;
        } catch (e) {
            return probe.exists;
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
        writeLog(jobPath, "blank_template=" + (job.blank_template || ""));
        writeLog(
            jobPath,
            "replacements=" + ((job.blank_text_replacements && job.blank_text_replacements.length) || 0)
        );
        writeLog(
            jobPath,
            "portrait_path=" + (job.portrait_path ? job.portrait_path : "none")
        );
        var templateFile = new File(job.template);
        var psdFile = new File(job.output_psd);
        var jpgFile = new File(job.output_jpg);
        var isPsb = job.output_is_psb === true || /\.psb$/i.test(job.template);
        var opened = openJobDocument(job, templateFile);
        var workName = opened.workName;
        gWorkName = workName;
        gTemplateName = opened.templateName;
        var renderError = null;
        writeLog(jobPath, "work doc " + workName + " duplicate=" + opened.isDuplicate);

        try {
            if (!activateByName(workName)) {
                throw new Error("Work document is not open: " + workName);
            }
            job._cardEdited = 0;
            logSmartObjects(app.activeDocument, "");
            applyJob(app.activeDocument, job, 0);
            writeLog(jobPath, "card SO edited: " + (job._cardEdited || 0));
            writeLog(jobPath, "portrait inserted=" + (job._portraitDone ? "yes" : "no"));
            if (job.template_name !== "mockup_blank" && (job._cardEdited || 0) < 1) {
                writeLog(jobPath, "Front in-place fallback: export-edit");
                fillCardSmartObjectsInPlace(app.activeDocument, job);
                writeLog(jobPath, "card SO edited: " + (job._cardEdited || 0));
            }
            closeOrphans();
            if (!activateByName(workName)) {
                throw new Error("Work document lost after applyJob");
            }
            saveMaster(workName, psdFile, isPsb);
            exportJpeg(workName, jpgFile);
        } catch (e) {
            renderError = e;
            writeLog(jobPath, "render error: " + e);
        }

        // The work document is either a duplicate or a dirty template:
        // always discard it so the cached template stays clean for the next job.
        try {
            closeByName(workName);
        } catch (eClose) {
            writeLog(jobPath, "close warn: " + eClose);
        }

        if (outputsExist(psdFile, jpgFile)) {
            writeLog(jobPath, "ok");
            return;
        }
        writeLog(
            jobPath,
            renderError
                ? ("fail: " + renderError)
                : ("fail: no output files " + psdFile.fsName)
        );
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
