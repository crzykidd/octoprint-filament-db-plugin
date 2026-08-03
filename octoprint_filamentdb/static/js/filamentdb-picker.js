// Copyright (C) 2026 crzykidd
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// OWNS: the picker modal's Knockout state and behaviour -- search query,
//     material/location/hide-retired filters, ranking the cache via
//     FilamentDBSearch.rank() (FR-2, no request per keystroke), the
//     default label-ascending sort (TODO(FR-9b): should be "most recently
//     used on this printer" once the write journal exists), whether the
//     Match column is showing at all (`pickerSearching` -- empty with no
//     active query, since an always-empty column reads as broken; fix 4,
//     2026-08-02 picker UI fixes), the duplicate-assignment confirmation,
//     and issuing the "assign" API command. Split out of filamentdb.js to
//     keep that file under the 500-line module cap (PRD N-1);
//     `FilamentDBPicker.attach(self)` is called once from
//     FilamentDBViewModel's constructor and adds these observables/
//     methods directly onto the shared viewmodel instance, so the sidebar
//     and picker templates bind against one `self` as usual.
// DOES NOT OWN: the ranking algorithm itself (filamentdb-search.js), the
//     weight computation (server-side only, weights.py -- each library
//     row already carries the `weightPickerText` api.py computed for this
//     column specifically, this file just renders it), resolving
//     locationId -> name (filamentdb.js's loadLibrary() denormalises
//     `locationName` onto each row before this file ever sees it), or the
//     library cache/sidebar rows it reads (`self.library`, `self.toolLabel`,
//     `self.toolForSpool`, `self.loadLibrary`, `self.libraryLoaded` -- all
//     set up by filamentdb.js before calling attach()).

(function (global) {
    "use strict";

    function tierLabel(tier) {
        if (!global.FilamentDBSearch) {
            return null;
        }
        switch (tier) {
            case FilamentDBSearch.TIER_EXACT_LABEL:
                return "exact label match";
            case FilamentDBSearch.TIER_EXACT_INSTANCE_ID:
                return "exact tag id match";
            case FilamentDBSearch.TIER_EXACT_ID:
                return "exact id match";
            case FilamentDBSearch.TIER_LABEL_PREFIX:
                return "label starts with your search";
            case FilamentDBSearch.TIER_INSTANCE_ID_PREFIX:
                return "tag id starts with your search";
            case FilamentDBSearch.TIER_FUZZY:
                return "fuzzy match";
            default:
                return null;
        }
    }

    function attach(self) {
        self.pickerToolIndex = ko.observable(null);
        self.pickerQuery = ko.observable("");
        self.pickerHideRetired = ko.observable(true);
        self.pickerTypeFilter = ko.observable(null);
        self.pickerLocationFilter = ko.observable(null);

        self.openPicker = function (toolIndex) {
            self.pickerToolIndex(toolIndex);
            self.pickerQuery("");
            self.pickerHideRetired(true);
            self.pickerTypeFilter(null);
            self.pickerLocationFilter(null);
            if (!self.libraryLoaded()) {
                self.loadLibrary();
            }
            $("#filamentdb_picker_modal").modal("show");
        };

        self.closePicker = function () {
            $("#filamentdb_picker_modal").modal("hide");
        };

        self.pickerTargetLabel = ko.pureComputed(function () {
            var toolIndex = self.pickerToolIndex();
            return toolIndex === null ? "" : self.toolLabel(toolIndex);
        });

        self.pickerMaterialTypes = ko.pureComputed(function () {
            var seen = {};
            self.library().forEach(function (row) {
                if (row.type) {
                    seen[row.type] = true;
                }
            });
            return Object.keys(seen).sort();
        });

        // {id, name} pairs, one per distinct locationId actually present in
        // the library, sorted by the resolved name -- not the raw id
        // (fix 5, 2026-08-02 picker UI fixes). A spool whose locationId
        // didn't resolve to a name (unknown/missing) is excluded from the
        // filter entirely rather than showing a blank or a GUID option.
        self.pickerLocations = ko.pureComputed(function () {
            var seen = {};
            self.library().forEach(function (row) {
                if (row.locationId && row.locationName) {
                    seen[row.locationId] = row.locationName;
                }
            });
            return Object.keys(seen)
                .map(function (id) {
                    return { id: id, name: seen[id] };
                })
                .sort(function (a, b) {
                    return a.name.localeCompare(b.name, undefined, { numeric: true });
                });
        });

        // Whether the Match column has anything to show at all -- ranking
        // (and therefore a tier) only exists while there's an active
        // query; with an empty search box, results come from the plain
        // label-ascending sort below and carry no tier. An always-present,
        // always-empty column reads as broken, so the template hides the
        // whole column (header included) when this is false (fix 4,
        // 2026-08-02 picker UI fixes).
        self.pickerSearching = ko.pureComputed(function () {
            return !!(self.pickerQuery() || "").trim();
        });

        self.pickerResults = ko.pureComputed(function () {
            var rows = self.library();

            if (self.pickerHideRetired()) {
                rows = rows.filter(function (r) {
                    return !r.retired;
                });
            }
            if (self.pickerTypeFilter()) {
                rows = rows.filter(function (r) {
                    return r.type === self.pickerTypeFilter();
                });
            }
            if (self.pickerLocationFilter()) {
                rows = rows.filter(function (r) {
                    return r.locationId === self.pickerLocationFilter();
                });
            }

            var query = (self.pickerQuery() || "").trim();
            var ranked;
            if (query && global.FilamentDBSearch) {
                ranked = FilamentDBSearch.rank(rows, query);
            } else {
                // TODO(FR-9b): default sort should be "most recently used
                // on this printer", sourced from the write journal, which
                // does not exist yet. For this step: label ascending.
                var sorted = rows.slice().sort(function (a, b) {
                    return (a.label || "").localeCompare(b.label || "", undefined, {
                        numeric: true,
                    });
                });
                ranked = sorted.map(function (row) {
                    return { row: row, tier: null };
                });
            }

            return ranked.map(function (result) {
                var row = result.row;
                var assignedTool = self.toolForSpool(row.spoolId);
                return {
                    row: row,
                    tierLabel: tierLabel(result.tier),
                    // Server-computed (C-2, weights.py) -- already on the
                    // row from filamentdb.js's loadLibrary(), no
                    // client-side arithmetic here. This is the picker
                    // column's own compact "net / gross" format, not the
                    // sidebar's full-ratio weightText (fix 2, 2026-08-02
                    // picker UI fixes).
                    weightText: row.weightPickerText,
                    // Overflow guard only (fix 1, 2026-08-02 picker UI
                    // fixes): the modal is widened so a typical filament
                    // line fits on one line; this is the full text for the
                    // `title` tooltip on the rare pathological name CSS
                    // still has to clip with an ellipsis, not a second
                    // rendering of the line.
                    filamentLineTitle:
                        "[" + (row.type || "") + "] " + (row.name || "") + " (" + (row.vendor || "") + ")",
                    swatch: row.color || "#808080",
                    alreadyAssigned: assignedTool !== null,
                    alreadyAssignedLabel:
                        assignedTool !== null
                            ? self.toolLabel(parseInt(assignedTool, 10))
                            : null,
                };
            });
        });

        self.selectSpool = function (pickerRow) {
            var proceed = function () {
                OctoPrint.simpleApiCommand("filamentdb", "assign", {
                    toolIndex: self.pickerToolIndex(),
                    spoolId: pickerRow.row.spoolId,
                })
                    .done(function (response) {
                        self.closePicker();
                        if (response.densityWarning && global.PNotify) {
                            new PNotify({
                                title: "Filament DB",
                                text:
                                    "This filament has no density set -- grams " +
                                    "consumed on this spool will be estimated.",
                                type: "warning",
                                // PNotify v2 -- the version OctoPrint ships --
                                // renders `text` as raw HTML by default. Set on
                                // every call site, not just the ones with
                                // non-literal text, so a later edit that
                                // interpolates a value cannot silently become an
                                // XSS vector (octoscanner SEC-0011).
                                text_escape: true,
                            });
                        }
                    })
                    .fail(function (xhr) {
                        if (global.PNotify) {
                            new PNotify({
                                title: "Filament DB",
                                // This one is the live vector: the value is a
                                // server error string, and api.py surfaces
                                // `str(exc)` from the Filament DB client -- so
                                // Filament-DB-controlled content (filament names,
                                // response bodies) reaches it. Rendered as raw
                                // HTML that is DOM XSS.
                                text:
                                    (xhr.responseJSON && xhr.responseJSON.error) ||
                                    "Could not assign spool",
                                type: "error",
                                text_escape: true,
                            });
                        }
                    });
            };

            if (pickerRow.alreadyAssigned && global.showConfirmationDialog) {
                showConfirmationDialog({
                    title: "Spool already assigned",
                    message:
                        "Spool #" +
                        pickerRow.row.label +
                        " is already assigned to " +
                        pickerRow.alreadyAssignedLabel +
                        ". Assign it here too?",
                    proceed: "Assign anyway",
                    onproceed: proceed,
                });
            } else {
                proceed();
            }
        };
    }

    global.FilamentDBPicker = { attach: attach };
})(window);
