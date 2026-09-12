#target photoshop
var OTRIS_JSX_VERSION = "2026-09-12.7";

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

    function updateTextGroupByIndex(doc, values, visibility, job) {
        if (!values || !values.length) {
            return;
        }
        var groups = [];
        findGroupsNamed(doc, "Text", groups);
        if (!(job && job._keepTextVisible && job.back_table_map)) {
            for (var g = 0; g < groups.length; g++) {
                if (groupHasDirectSmartObject(groups[g]) && !groupHasDirectTextLayers(groups[g])) {
                    continue;
                }
                var textLayers = [];
                collectTextLayers(groups[g], textLayers, true);
                if (textLayers.length < values.length) {
                    textLayers = [];
                    collectTextLayers(groups[g], textLayers, false);
                }
                writeLog(
                    null,
                    "text-group slots=" + textLayers.length + " values=" + values.length +
                        " in '" + docName(doc) + "'"
                );
                for (var i = 0; i < textLayers.length; i++) {
                    var val = i < values.length ? values[i] : "";
                    var vis = !visibility || i >= visibility.length ? true : visibility[i];
                    setTextSafe(textLayers[i], val, vis);
                }
            }
        }
        if (job && job._keepTextVisible && !job._stampDates) {
            fillDateLikeLayers(doc, values, visibility);
        }
    }

    function layerMid(layer) {
        try {
            var b = layer.bounds;
            return {
                x: (b[0].as("px") + b[2].as("px")) / 2,
                y: (b[1].as("px") + b[3].as("px")) / 2
            };
        } catch (e) {
            return { x: 0, y: 0 };
        }
    }

    function isFillableDateCell(layer) {
        var t = layerTextContents(layer).replace(/\s+/g, "");
        if (/^[дdмmгgyYxXхХ0]{1,2}[.\-\/][дdмmгgyYxXхХ0]{1,2}[.\-\/][дdмmгgyYxXхХ0]{2,4}$/i.test(t)) {
            return true;
        }
        if (/^\d{2}[.\-]\d{2}[.\-]\d{4}$/.test(t)) {
            return true;
        }
        if (/^[0xXхХ.·\-—_]{4,}$/.test(t)) {
            return true;
        }
        if (t === "—" || t === "-" || t === "…" || t === "–") {
            return true;
        }
        return isDateLikeLayer(layer);
    }

    function isLandscapeCardDoc(doc) {
        try {
            var a = doc.width.as("px") / doc.height.as("px");
            return a > 1.32 && a < 1.9;
        } catch (e) {
            return false;
        }
    }

    function applyBackTableDates(doc, job) {
        if (!(job && job._stampDates)) {
            writeLog(null, "back table skip: not in Back SO '" + docName(doc) + "'");
            return;
        }
        if (!isLandscapeCardDoc(doc)) {
            writeLog(null, "back table skip: not card-sized '" + docName(doc) + "'");
            return;
        }
        var table = resolveBackTable(job) || {};
        var order = (job && job.back_table_order) || [
            "A", "A1", "B", "B1", "C", "C1", "D", "D1",
            "BE", "CE", "DE", "Tm", "Tb", "M"
        ];
        var stampKey = "backDates:" + docName(doc);
        if (job._stampedDocs && job._stampedDocs[stampKey]) {
            writeLog(null, "back table dates already stamped in '" + docName(doc) + "'");
            return;
        }
        logBackTextDump(doc);
        var stamped = stampBackTableDates(doc, job, table, order);
        job._stampedDocs = job._stampedDocs || {};
        job._stampedDocs[stampKey] = true;
        writeLog(
            null,
            "back table dates named=0 grid=0 stamped=" + stamped +
                " pt=" + ((job && job._lastStampPt) || "?") +
                " in '" + docName(doc) + "'"
        );
    }

    function logBackTextDump(doc) {
        var layers = [];
        collectTextLayers(doc, layers, false);
        writeLog(null, "back text dump n=" + layers.length + " '" + docName(doc) + "'");
        var i;
        var n = layers.length > 50 ? 50 : layers.length;
        for (i = 0; i < n; i++) {
            var m = layerMid(layers[i]);
            var nm = "";
            try {
                nm = String(layers[i].name || "");
            } catch (eN) {}
            var t = layerTextContents(layers[i]).replace(/\s+/g, " ").slice(0, 36);
            writeLog(null, "  T '" + nm + "' '" + t + "' x=" + Math.round(m.x) + " y=" + Math.round(m.y));
        }
    }

    var BACK_ROW_INDEX = {
        A: 0, A1: 1, B: 2, B1: 3, C: 4, C1: 5, D: 6, D1: 7,
        BE: 8, CE: 9, C1E: 10, DE: 11, D1E: 12, M: 13, Tm: 14, Tb: 15
    };
    var BACK_ROW_FRAC = {
        A: 0.088, A1: 0.1425, B: 0.197, B1: 0.2515,
        C: 0.306, C1: 0.3605, D: 0.415, D1: 0.4695,
        BE: 0.524, CE: 0.5785, C1E: 0.633, DE: 0.6875,
        D1E: 0.742, M: 0.7965, Tm: 0.851, Tb: 0.9055
    };

    function tableRowY(box, job, cat) {
        var key = String(cat || "").toUpperCase();
        var frac = backRowFrac(job, key, BACK_ROW_FRAC[key] || 0.249);
        return box.y + box.h * frac;
    }

    function backRowFrac(job, cat, fallback) {
        var rows = (job && job.back_table_geom && job.back_table_geom.rows) || BACK_ROW_FRAC;
        var key = String(cat || "").toUpperCase();
        if (rows[cat] != null) {
            return Number(rows[cat]);
        }
        if (rows[key] != null) {
            return Number(rows[key]);
        }
        if (BACK_ROW_FRAC[key] != null) {
            return BACK_ROW_FRAC[key];
        }
        return fallback;
    }

    function backTableGeom(doc, job) {
        var g = (job && job.back_table_geom) || {};
        var W = doc.width.as("px");
        var H = doc.height.as("px");
        return {
            w: W,
            h: H,
            col10: (g.col10 || 0.610) * W,
            col11: (g.col11 || 0.790) * W,
            top: (g.top || 0.115) * H,
            bottom: (g.bottom || 0.850) * H
        };
    }

    function stampBackTableDates(doc, job, table, order) {
        var geom = backTableGeom(doc, job);
        if (geom.w <= 0 || geom.h <= 0) {
            return 0;
        }
        var rowH = geom.h * 0.0545;
        var style = backDateTextStyle(doc, geom, rowH);
        if (job) {
            job._lastStampPt = style.sizePt;
        }
        writeLog(null, "stamp style pt=" + style.sizePt + " card=" + Math.round(geom.w) + "x" + Math.round(geom.h));
        var n = 0;
        var cats = order && order.length ? order : ["B", "B1", "M"];
        var i;
        for (i = 0; i < cats.length; i++) {
            var cat = cats[i];
            var data = table[cat];
            if (!data || !data.open) {
                continue;
            }
            var y = tableRowY({y: 0, h: geom.h}, job, cat);
            n += placeBackDate(doc, data.open, geom.col10, y, style, "vu_10_" + cat);
            if (data.expiry) {
                n += placeBackDate(doc, data.expiry, geom.col11, y, style, "vu_11_" + cat);
            }
        }
        return n;
    }

    function layerWidth(layer) {
        try {
            var b = layer.bounds;
            return Math.abs(b[2].as("px") - b[0].as("px"));
        } catch (e) {
            return 0;
        }
    }

    function isStampDateLayer(layer) {
        var nm = "";
        try {
            nm = String(layer.name || "");
        } catch (e) {}
        return /^vu_1[01]_/i.test(nm);
    }

    function placeBackDate(doc, text, x, y, style, layerName) {
        if (createBackDateLayer(doc, text, x, y, style, layerName)) {
            return 1;
        }
        return 0;
    }

    function findLayerNear(layers, x, y, maxDx, maxDy) {
        var best = null;
        var bestD = 1e12;
        var i;
        for (i = 0; i < layers.length; i++) {
            var m = layerMid(layers[i]);
            var dx = Math.abs(m.x - x);
            var dy = Math.abs(m.y - y);
            if (dx > maxDx || dy > maxDy) {
                continue;
            }
            var d = dx + dy * 1.4;
            if (d < bestD) {
                bestD = d;
                best = layers[i];
            }
        }
        return best;
    }

    function backDateTextStyle(doc, geom, rowH) {
        var ppi = 72;
        try {
            ppi = Number(doc.resolution) || 72;
        } catch (eR) {}
        if (ppi < 36) {
            ppi = 72;
        }
        // ~62% высоты строки таблицы — как печать в графах 10/11
        var sizePx = rowH > 0 ? rowH * 0.62 : geom.h * 0.033;
        if (sizePx < 8) {
            sizePx = 8;
        }
        if (rowH > 0 && sizePx > rowH * 0.78) {
            sizePx = rowH * 0.78;
        }
        var sizePt = sizePx * 72 / ppi;
        return {
            sizePt: sizePt,
            font: "ArialMT",
            color: null
        };
    }

    function createBackDateLayer(doc, text, xPx, yPx, style, layerName) {
        try {
            app.activeDocument = doc;
        } catch (eAct) {}
        var group = null;
        var groups = [];
        findGroupsNamed(doc, "Text", groups);
        if (groups.length) {
            group = groups[0];
            try {
                group.visible = true;
                doc.activeLayer = group;
            } catch (eG) {}
        }
        var layer;
        try {
            layer = doc.artLayers.add();
        } catch (eAdd) {
            writeLog(null, "stamp date add failed: " + eAdd);
            return false;
        }
        try {
            layer.kind = LayerKind.TEXT;
        } catch (eKind) {}
        try {
            layer.name = layerName || "vu_date";
        } catch (eNm) {}
        try {
            var ti = layer.textItem;
            ti.kind = TextType.POINTTEXT;
            ti.contents = String(text);
            try {
                ti.font = style.font || "ArialMT";
            } catch (eF) {
                try {
                    ti.font = "ArialMT";
                } catch (eF2) {}
            }
            try {
                ti.size = style.sizePt || 5;
            } catch (eSz) {}
            try {
                ti.justification = Justification.CENTER;
            } catch (eJ) {}
            try {
                if (style.color) {
                    ti.color = style.color;
                } else {
                    var c = new SolidColor();
                    c.rgb.red = 28;
                    c.rgb.green = 28;
                    c.rgb.blue = 32;
                    ti.color = c;
                }
            } catch (eCol) {}
            ti.position = [new UnitValue(xPx, "px"), new UnitValue(yPx, "px")];
        } catch (eTxt) {
            writeLog(null, "stamp date text failed: " + eTxt);
            try {
                layer.remove();
            } catch (eRm) {}
            return false;
        }
        if (group) {
            try {
                layer.move(group, ElementPlacement.INSIDE);
            } catch (eMv) {
                try {
                    layer.move(group, ElementPlacement.PLACEATBEGINNING);
                } catch (eMv2) {}
            }
        }
        writeLog(null, "stamp date '" + layerName + "' = " + text + " @ " + Math.round(xPx) + "," + Math.round(yPx));
        return true;
    }

    function fillBackByCategoryName(doc, table) {
        var n = 0;
        var cat;
        for (cat in table) {
            if (!table.hasOwnProperty(cat) || !table[cat]) {
                continue;
            }
            var groups = [];
            findGroupsNamed(doc, cat, groups);
            findGroupsNamed(doc, String(cat).toLowerCase(), groups);
            var g;
            for (g = 0; g < groups.length; g++) {
                var cells = [];
                collectTextLayers(groups[g], cells, false);
                var dates = [];
                var i;
                for (i = 0; i < cells.length; i++) {
                    if (isFillableDateCell(cells[i])) {
                        dates.push(cells[i]);
                    }
                }
                dates.sort(function (a, b) {
                    var am = layerMid(a);
                    var bm = layerMid(b);
                    if (Math.abs(am.y - bm.y) > 8) {
                        return am.y - bm.y;
                    }
                    return am.x - bm.x;
                });
                if (dates[0] && table[cat].open) {
                    setTextSafe(dates[0], table[cat].open, true);
                    n++;
                }
                if (dates[1] && table[cat].expiry) {
                    setTextSafe(dates[1], table[cat].expiry, true);
                    n++;
                }
            }
        }
        return n;
    }

    function fillBackByGrid(doc, table, order) {
        var groups = [];
        findGroupsNamed(doc, "Text", groups);
        var layers = [];
        var g;
        if (groups.length) {
            for (g = 0; g < groups.length; g++) {
                if (groupHasDirectSmartObject(groups[g]) && !groupHasDirectTextLayers(groups[g])) {
                    continue;
                }
                collectTextLayers(groups[g], layers, false);
            }
        } else {
            collectTextLayers(doc, layers, false);
        }
        var cells = [];
        var i;
        var minX = doc.width.as("px") * 0.42;
        for (i = 0; i < layers.length; i++) {
            if (layerMid(layers[i]).x < minX) {
                continue;
            }
            if (isFillableDateCell(layers[i])) {
                cells.push(layers[i]);
            }
        }
        if (cells.length < 2) {
            return 0;
        }
        cells.sort(function (a, b) {
            var am = layerMid(a);
            var bm = layerMid(b);
            if (Math.abs(am.y - bm.y) > 10) {
                return am.y - bm.y;
            }
            return am.x - bm.x;
        });
        var rows = [];
        var cur = [cells[0]];
        var lastY = layerMid(cells[0]).y;
        for (i = 1; i < cells.length; i++) {
            var y = layerMid(cells[i]).y;
            if (Math.abs(y - lastY) > 14) {
                rows.push(cur);
                cur = [cells[i]];
            } else {
                cur.push(cells[i]);
            }
            lastY = y;
        }
        rows.push(cur);
        var active = [];
        for (i = 0; i < order.length; i++) {
            if (table[order[i]] && table[order[i]].open) {
                active.push(order[i]);
            }
        }
        var useOrder = (rows.length <= 6 && active.length) ? active : order;
        var n = 0;
        for (i = 0; i < rows.length; i++) {
            var cat = i < useOrder.length ? useOrder[i] : "";
            var data = cat ? table[cat] : null;
            if (!data || !data.open) {
                continue;
            }
            var cols = rows[i].slice();
            cols.sort(function (a, b) {
                return layerMid(a).x - layerMid(b).x;
            });
            if (cols[0]) {
                setTextSafe(cols[0], data.open, true);
                n++;
            }
            if (cols[1] && data.expiry) {
                setTextSafe(cols[1], data.expiry, true);
                n++;
            }
        }
        return n;
    }

    function layerTextContents(layer) {
        try {
            return String(layer.textItem.contents || "");
        } catch (e) {
            return "";
        }
    }

    function isDateLikeLayer(layer) {
        var t = layerTextContents(layer).replace(/^\s+|\s+$/g, "");
        var n = "";
        try {
            n = String(layer.name || "");
        } catch (eN) {}
        if (/^\d{2}[.\-]\d{2}[.\-]\d{4}$/.test(t) || /^\d{2}[.\-]\d{2}[.\-]\d{4}$/.test(n)) {
            return true;
        }
        if (/^(10|11|12|open|expiry|открыто|до)$/i.test(n.replace(/^\s+|\s+$/g, ""))) {
            return true;
        }
        return false;
    }

    function fillDateLikeLayers(doc, values, visibility) {
        if (!values || !values.length) {
            return;
        }
        var layers = [];
        collectTextLayers(doc, layers, false);
        var dates = [];
        var i;
        for (i = 0; i < values.length; i++) {
            if (/^\d{2}\.\d{2}\.\d{4}$/.test(String(values[i] || ""))) {
                dates.push({ value: values[i], vis: !visibility || visibility[i] !== false });
            }
        }
        if (!dates.length) {
            return;
        }
        var di = 0;
        var filled = 0;
        for (i = 0; i < layers.length; i++) {
            if (di >= dates.length) {
                break;
            }
            if (!isDateLikeLayer(layers[i])) {
                continue;
            }
            if (setTextSafe(layers[i], dates[di].value, dates[di].vis)) {
                filled++;
                di++;
            }
        }
        if (filled) {
            writeLog(null, "date-like layers filled=" + filled + " in '" + docName(doc) + "'");
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

    function countNamedLayers(doc, name) {
        var n = 0;
        if (!name) {
            return 0;
        }
        forEachLayerByName(doc, name, function () {
            n++;
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
                    n++;
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
            if (isBackCardName(cards[i])) {
                toggleNamedLayers(doc, cards[i], false);
                continue;
            }
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

    function scaleActiveLayerFit(doc) {
        var layer = doc.activeLayer;
        var b = layer.bounds;
        var w = b[2].as("px") - b[0].as("px");
        var h = b[3].as("px") - b[1].as("px");
        var cw = doc.width.as("px");
        var ch = doc.height.as("px");
        if (w <= 0 || h <= 0) {
            return;
        }
        var scale = Math.min(cw / w, ch / h) * 100;
        layer.resize(scale, scale, AnchorPosition.MIDDLECENTER);
        b = layer.bounds;
        var cx = (b[0].as("px") + b[2].as("px")) / 2;
        var cy = (b[1].as("px") + b[3].as("px")) / 2;
        layer.translate(cw / 2 - cx, ch / 2 - cy);
    }

    function placeImageInDoc(doc, imagePath, fit) {
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
        if (fit) {
            scaleActiveLayerFit(doc);
        } else {
            scaleLayerToCanvas(doc);
        }
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

    function fillDocPaperGray(doc) {
        var c = new SolidColor();
        c.rgb.red = 228;
        c.rgb.green = 228;
        c.rgb.blue = 228;
        try {
            app.activeDocument = doc;
        } catch (eAct) {}
        try {
            if (doc.backgroundLayer) {
                doc.activeLayer = doc.backgroundLayer;
                doc.selection.selectAll();
                doc.selection.fill(c, ColorBlendMode.NORMAL, 100, false);
                doc.selection.deselect();
            }
        } catch (eBg) {}
        var paper = null;
        try {
            paper = doc.artLayers.add();
            paper.name = "vu_photo_paper";
            doc.selection.selectAll();
            doc.selection.fill(c, ColorBlendMode.NORMAL, 100, false);
            doc.selection.deselect();
            try {
                paper.move(doc.layers[doc.layers.length - 1], ElementPlacement.PLACEAFTER);
            } catch (eMv) {}
        } catch (eAdd) {
            writeLog(null, "photo paper fill failed: " + eAdd);
        }
        return paper;
    }

    function keepPortraitLayer(layer, photo, paper) {
        if (!layer) {
            return false;
        }
        if (layer === photo || layer === paper) {
            return true;
        }
        try {
            if (String(layer.name || "") === "vu_photo_paper") {
                return true;
            }
        } catch (eN) {}
        try {
            if (layer.isBackgroundLayer) {
                return true;
            }
        } catch (eB) {}
        return false;
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
            writeLog(
                null,
                "photo SO canvas " +
                    Math.round(innerDoc.width.as("px")) + "x" +
                    Math.round(innerDoc.height.as("px"))
            );
            var paper = fillDocPaperGray(innerDoc);
            var before = innerDoc.layers.length;
            placeImageInDoc(innerDoc, imagePath, true);
            if (innerDoc.layers.length <= before) {
                writeLog(null, "portrait place failed: " + imagePath);
                return;
            }
            scaleActiveLayerFit(innerDoc);
            try {
                var photo = innerDoc.activeLayer;
                var i;
                for (i = innerDoc.layers.length - 1; i >= 0; i--) {
                    var L = innerDoc.layers[i];
                    if (keepPortraitLayer(L, photo, paper)) {
                        continue;
                    }
                    try {
                        L.remove();
                    } catch (e1) {}
                }
                try {
                    innerDoc.activeLayer = photo;
                    photo.merge();
                } catch (eMg) {}
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
                        layer.visible = !isBackCardName(layer.name);
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
                        job._editedSO = job._editedSO || {};
                        var lid = "";
                        try {
                            lid = String(layer.id);
                        } catch (eId) {
                            lid = cardName + "_" + i + "_" + depth;
                        }
                        if (job._editedSO[lid]) {
                            writeLog(null, "skip already edited SO: " + layer.name);
                        } else {
                            job._editedSO[lid] = true;
                            writeLog(null, "edit card SO in place: " + layer.name);
                            var prevKeep = job._keepTextVisible;
                            var prevStamp = job._stampDates;
                            if (isBackCardName(cardName)) {
                                job._keepTextVisible = true;
                                job._stampDates = true;
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
                                job._stampDates = false;
                                walkLayers(innerDoc.layers, job, depth + 1);
                            }, true);
                            job._keepTextVisible = prevKeep;
                            job._stampDates = prevStamp;
                            if (isBackCardName(cardName)) {
                                try {
                                    layer.visible = false;
                                } catch (eHidBack) {}
                            }
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
            updateTextGroupByIndex(doc, textVals || [], textVis || null, job);
        } catch (eGrp) {
            writeLog(null, "updateTextGroupByIndex: " + eGrp);
        }
        try {
            if (job && job._stampDates) {
                applyBackTableDates(doc, job);
            }
        } catch (eBackTbl) {
            writeLog(null, "applyBackTableDates: " + eBackTbl);
        }
        try {
            if (!(job && job._keepTextVisible)) {
                hideGroupsNamed(doc, "Text");
            } else {
                writeLog(null, "keep Text visible (back side) in '" + docName(doc) + "'");
            }
        } catch (eHide) {}
        if (hits < 1) {
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
        if (n === "Text" || n === "text" || n === "TEXT" || n === "Front" || n === "front"
                || n === "Back" || n === "back") {
            return true;
        }
        if (/^front$|^back$|^text$|card|licence|license|оборот/i.test(n)) {
            return true;
        }
        return false;
    }

    function isBackCardName(n) {
        var k = String(n || "").toLowerCase();
        return k === "back" || k === "reverse" || k.indexOf("оборот") >= 0;
    }

    function cardSideNames(job, side) {
        var scene = (job && job.scene) || {};
        var i;
        if (side === "back") {
            var named = scene.back_smart_objects || [];
            if (named && named.length) {
                return named;
            }
            return ["Back", "back", "оборот", "Reverse", "reverse"];
        }
        var fronts = scene.card_smart_objects || ["Front"];
        var out = [];
        for (i = 0; i < fronts.length; i++) {
            if (!isBackCardName(fronts[i])) {
                out.push(fronts[i]);
            }
        }
        if (!out.length) {
            out = ["Front", "front"];
        }
        return out;
    }

    function showBackTextGroups(doc) {
        var groups = [];
        findGroupsNamed(doc, "Text", groups);
        var n = 0;
        var i;
        for (i = 0; i < groups.length; i++) {
            var g = groups[i];
            if (groupHasDirectSmartObject(g) && !groupHasDirectTextLayers(g)) {
                continue;
            }
            if (!groupHasDirectTextLayers(g)) {
                continue;
            }
            try {
                g.visible = true;
                n++;
            } catch (eVis) {}
        }
        forEachLayerByName(doc, "Text", function (layer) {
            if (layer.typename === "ArtLayer") {
                try {
                    layer.visible = true;
                    n++;
                } catch (eArt) {}
            }
        });
        if (n) {
            writeLog(null, "show back Text groups=" + n + " in '" + docName(doc) + "'");
        }
        return n;
    }

    function shouldEnterForCardSide(layer, job, loose) {
        if (!isSmartObject(layer)) {
            return false;
        }
        var scene = (job && job.scene) || {};
        var n = "";
        try {
            n = String(layer.name);
        } catch (e) {
            return false;
        }
        if (isPhotoName(n, job)) {
            return false;
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
        if (scene.hand_smart_object && n === scene.hand_smart_object) {
            return false;
        }
        if (nameInList(n, scene.skip_smart_objects || job.skip_smart_objects)) {
            return false;
        }
        if (isCardSmartObject(layer, job) || isWrapperSmartObject(layer, job)) {
            return true;
        }
        return !!loose;
    }

    function showCardSide(doc, job, side, depth) {
        depth = depth || 0;
        var show = cardSideNames(job, side);
        var hide = cardSideNames(job, side === "back" ? "front" : "back");
        var shownHere = 0;
        var shown = 0;
        var textShown = 0;
        var i;
        for (i = 0; i < show.length; i++) {
            shownHere += countNamedLayers(doc, show[i]);
        }
        if (shownHere > 0) {
            for (i = 0; i < hide.length; i++) {
                toggleNamedLayers(doc, hide[i], false);
            }
            for (i = 0; i < show.length; i++) {
                shown += toggleNamedLayers(doc, show[i], true);
            }
        }
        try {
            if (side === "back") {
                textShown = showBackTextGroups(doc);
                toggleNamedLayers(doc, "Text", true);
            } else {
                hideGroupsNamed(doc, "Text");
            }
        } catch (eTxtSide) {}
        if (shown < 1 && textShown > 0 && side === "back") {
            shown = textShown;
        }
        if (shown < 1 && depth < 5) {
            shown += showCardSideInSmartObjects(doc, job, side, depth + 1);
        }
        writeLog(
            null,
            "card side '" + side + "' shown=" + shown + " depth=" + depth +
                " here=" + shownHere + " text=" + textShown
        );
        return shown > 0;
    }

    function showCardSideInSmartObjects(doc, job, side, depth) {
        var n = 0;
        function walk(layers, loose) {
            var i;
            for (i = 0; i < layers.length; i++) {
                var layer = layers[i];
                if (!layer) {
                    continue;
                }
                if (layer.typename === "LayerSet") {
                    walk(layer.layers, loose);
                } else if (layer.typename === "ArtLayer" && shouldEnterForCardSide(layer, job, loose)) {
                    writeLog(null, "card side enter SO '" + layer.name + "' for '" + side + "'");
                    editSmartObject(layer, function (innerDoc) {
                        if (showCardSide(innerDoc, job, side, depth)) {
                            n++;
                        }
                    }, true);
                }
            }
        }
        try {
            walk(doc.layers, false);
            if (n < 1) {
                walk(doc.layers, true);
            }
        } catch (eW) {
            writeLog(null, "showCardSide SO: " + eW);
        }
        return n;
    }

    function layerBox(layer) {
        try {
            var b = layer.bounds;
            var x = b[0].as("px");
            var y = b[1].as("px");
            return {
                x: x,
                y: y,
                w: b[2].as("px") - x,
                h: b[3].as("px") - y,
                name: String(layer.name || "")
            };
        } catch (e) {
            return null;
        }
    }

    function inferCardFromTallBox(box) {
        if (!box || box.w < 120 || box.h < 80) {
            return null;
        }
        var w = box.w * 0.94;
        var h = w / 1.585;
        if (h > box.h * 0.72) {
            h = box.h * 0.58;
            w = h * 1.585;
        }
        return {
            x: box.x + (box.w - w) / 2,
            y: box.y + box.h - h - box.h * 0.03,
            w: w,
            h: h,
            name: "inferred:" + box.name
        };
    }

    function findVisibleCardBounds(doc, job) {
        var docW = doc.width.as("px");
        var docH = doc.height.as("px");
        var docA = docW * docH;
        var names = cardSideNames(job, "back");
        var best = null;
        var bestScore = 1e12;
        var tall = null;
        var tallA = 0;

        function considerBox(box, namedBack) {
            if (!box || box.w < 100 || box.h < 60) {
                return;
            }
            var area = box.w * box.h;
            var areaFrac = area / docA;
            var aspect = box.w / box.h;
            if (areaFrac > 0.08 && areaFrac < 0.55 && area > tallA) {
                tall = box;
                tallA = area;
            }
            if (areaFrac > 0.42 || areaFrac < 0.035) {
                return;
            }
            if (aspect < 1.28 || aspect > 1.95) {
                return;
            }
            var s = Math.abs(aspect - 1.585) * 8 + areaFrac;
            if (namedBack) {
                s -= 0.4;
            }
            writeLog(
                null,
                "card cand '" + box.name + "' " + Math.round(box.w) + "x" + Math.round(box.h) +
                    " a=" + Math.round(aspect * 100) / 100 + " frac=" + Math.round(areaFrac * 100) / 100
            );
            if (s < bestScore) {
                bestScore = s;
                best = box;
            }
        }

        function walk(layers) {
            var i;
            for (i = 0; i < layers.length; i++) {
                var layer = layers[i];
                if (!isVisible(layer)) {
                    continue;
                }
                var n = "";
                try {
                    n = String(layer.name);
                } catch (eN) {}
                var named = nameInList(n, names) || isBackCardName(n);
                var box = layerBox(layer);
                if (layer.typename === "ArtLayer") {
                    considerBox(box, named);
                } else if (layer.typename === "LayerSet") {
                    if (named) {
                        considerBox(box, true);
                    }
                    try {
                        walk(layer.layers);
                    } catch (eG) {}
                }
            }
        }
        try {
            walk(doc.layers);
        } catch (eW) {}
        if (!best && tall) {
            best = inferCardFromTallBox(tall);
            writeLog(null, "card inferred from '" + tall.name + "'");
        }
        return best;
    }

    function fallbackHandCardBox(doc) {
        var W = doc.width.as("px");
        var H = doc.height.as("px");
        var w = W * 0.50;
        var h = w / 1.585;
        if (h > H * 0.36) {
            h = H * 0.30;
            w = h * 1.585;
        }
        return {
            x: (W - w) / 2,
            y: H * 0.275,
            w: w,
            h: h,
            name: "fallback-hand"
        };
    }

    function pickJobDates(job) {
        var f = (job && job.fields) || {};
        var lf = (job && job.layers_by_field) || {};
        return {
            open: String(f.issue_date || lf.issue_date || ""),
            expiry: String(f.expiry_date || lf.expiry_date || "")
        };
    }

    function resolveBackTable(job) {
        var table = {};
        var src = (job && job.back_table_map) || {};
        if (!src || !src.B) {
            if (job && job.fields && job.fields.back_table) {
                src = job.fields.back_table;
            }
        }
        var cat;
        for (cat in src) {
            var row = src[cat];
            if (row && row.open) {
                table[String(cat)] = {
                    open: String(row.open),
                    expiry: String(row.expiry || "")
                };
            }
        }
        var has = false;
        for (cat in table) {
            has = true;
            break;
        }
        if (has) {
            return table;
        }
        var d = pickJobDates(job);
        if (!d.open) {
            writeLog(null, "scene dates: no 4a/4b in job");
            return null;
        }
        var cats = (job && job.fields && job.fields.categories) || ["B", "B1", "M"];
        if (!cats.length) {
            cats = ["B", "B1", "M"];
        }
        var i;
        for (i = 0; i < cats.length; i++) {
            table[String(cats[i]).toUpperCase()] = {open: d.open, expiry: d.expiry};
        }
        writeLog(null, "scene dates from 4a/4b " + d.open);
        return table;
    }

    function overlaySceneBackDates(doc, job) {
        var created = [];
        var table = resolveBackTable(job);
        if (!table) {
            writeLog(null, "scene dates: no table");
            return created;
        }
        try {
            app.activeDocument = doc;
        } catch (eAct) {}
        var box = findVisibleCardBounds(doc, job);
        if (box && box.w / box.h < 1.35) {
            var inferred = inferCardFromTallBox(box);
            if (inferred) {
                box = inferred;
            }
        }
        if (!box) {
            box = fallbackHandCardBox(doc);
            writeLog(null, "scene dates: using fallback card box");
        }
        writeLog(
            null,
            "scene dates card " + Math.round(box.w) + "x" + Math.round(box.h) +
                " @ " + Math.round(box.x) + "," + Math.round(box.y)
        );
        var g = (job && job.back_table_geom) || {};
        var col10 = box.x + (g.col10 || 0.610) * box.w;
        var col11 = box.x + (g.col11 || 0.790) * box.w;
        var ppi = 72;
        try {
            ppi = Number(doc.resolution) || 72;
        } catch (eR) {}
        if (ppi < 36) {
            ppi = 72;
        }
        var rowH = box.h * 0.0545;
        var sizePt = (rowH * 0.62) * 72 / ppi;
        if (sizePt < 6) {
            sizePt = 6;
        }
        var only = {B: 1, B1: 1, M: 1};
        var cat;
        for (cat in table) {
            if (!only[String(cat).toUpperCase()]) {
                continue;
            }
            var data = table[cat];
            if (!data || !data.open) {
                continue;
            }
            var y = tableRowY(box, job, cat);
            var a = createSceneDateLayer(doc, data.open, col10, y, sizePt, "vu_sc_10_" + cat);
            if (a) {
                created.push(a);
            }
            if (data.expiry) {
                var b = createSceneDateLayer(doc, data.expiry, col11, y, sizePt, "vu_sc_11_" + cat);
                if (b) {
                    created.push(b);
                }
            }
        }
        writeLog(null, "scene dates overlaid=" + created.length + " pt=" + sizePt);
        return created;
    }

    function createSceneDateLayer(doc, text, xPx, yPx, sizePt, layerName) {
        try {
            app.activeDocument = doc;
            try {
                doc.activeLayer = doc.layers[0];
            } catch (eTop) {}
            var layer = doc.artLayers.add();
            try {
                layer.kind = LayerKind.TEXT;
            } catch (eK) {}
            try {
                layer.name = layerName || "vu_sc_date";
            } catch (eN) {}
            var ti = layer.textItem;
            ti.kind = TextType.POINTTEXT;
            ti.contents = String(text);
            try {
                ti.font = "ArialMT";
            } catch (eF) {}
            try {
                ti.size = sizePt;
            } catch (eS) {}
            try {
                ti.justification = Justification.CENTER;
            } catch (eJ) {}
            try {
                var c = new SolidColor();
                c.rgb.red = 22;
                c.rgb.green = 22;
                c.rgb.blue = 26;
                ti.color = c;
            } catch (eC) {}
            ti.position = [new UnitValue(xPx, "px"), new UnitValue(yPx, "px")];
            writeLog(null, "scene date '" + layerName + "' = " + text + " @ " + Math.round(xPx) + "," + Math.round(yPx));
            return layer;
        } catch (e) {
            writeLog(null, "scene date add failed: " + e);
            return null;
        }
    }

    function removeOverlayLayers(layers) {
        if (!layers) {
            return;
        }
        var i;
        for (i = 0; i < layers.length; i++) {
            try {
                layers[i].remove();
            } catch (eRm) {}
        }
    }

    function exportBackJpeg(workName, job, jpgBack) {
        if (!jpgBack) {
            writeLog(null, "back jpeg: no output path");
            return false;
        }
        if (!activateByName(workName)) {
            writeLog(null, "back jpeg: work doc lost");
            return false;
        }
        var flipped = false;
        try {
            flipped = showCardSide(app.activeDocument, job, "back", 0);
        } catch (eSide) {
            writeLog(null, "back jpeg: show side failed: " + eSide);
        }
        if (!flipped) {
            writeLog(null, "back jpeg: no Back layer at top, tried card SO / Text");
        }
        var overlays = [];
        try {
            overlays = overlaySceneBackDates(app.activeDocument, job);
        } catch (eOv) {
            writeLog(null, "scene dates overlay: " + eOv);
            overlays = [];
        }
        try {
            exportJpeg(workName, jpgBack);
            var ok = fileReady(jpgBack);
            writeLog(null, ok
                ? ("back jpeg saved (" + fileSize(jpgBack) + " bytes)")
                : "back jpeg missing after export");
            return ok;
        } catch (eBack) {
            writeLog(null, "back jpeg failed: " + eBack);
            return false;
        } finally {
            removeOverlayLayers(overlays);
            try {
                if (activateByName(workName)) {
                    showCardSide(app.activeDocument, job, "front", 0);
                }
            } catch (eRest) {}
        }
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
                        var prevKeep = job._keepTextVisible;
                        var prevStamp = job._stampDates;
                        try {
                            if (isBackCardName(layer.name)) {
                                job._keepTextVisible = true;
                                job._stampDates = true;
                            }
                        } catch (eBn) {}
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
                        job._keepTextVisible = prevKeep;
                        job._stampDates = prevStamp;
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
                    if (isCardSmartObject(layer, job) && !isBackCardName(layer.name)) {
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
        updateTextGroupByIndex(doc, job.text_group_values || [], job.text_group_visibility || null, job);
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
            showCardSide(app.activeDocument, job, "front", 0);
            saveMaster(workName, psdFile, isPsb);
            exportJpeg(workName, jpgFile);
            if (job.output_jpg_back) {
                var backOk = exportBackJpeg(workName, job, new File(job.output_jpg_back));
                writeLog(jobPath, backOk ? "back jpeg ok" : "back jpeg missing");
            }
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
