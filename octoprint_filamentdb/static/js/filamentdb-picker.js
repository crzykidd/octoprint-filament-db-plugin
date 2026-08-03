// Copyright (C) 2026 crzykidd
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// OWNS: the picker modal's Knockout state and behaviour -- search query,
//     material/location/hide-retired filters, ranking the cache via
//     FilamentDBSearch.rank() (FR-2, no request per keystroke), the
//     default label-ascending sort (TODO(FR-9b): should be "most recently
//     used on this printer" once the write journal exists), the
//     duplicate-assignment confirmation, and issuing the "assign" API
//     command. Split out of filamentdb.js to keep that file under the
//     500-line module cap (PRD N-1); `FilamentDBPicker.attach(self)` is
//     called once from FilamentDBViewModel's constructor and adds these
//     observables/methods directly onto the shared viewmodel instance, so
//     the sidebar and picker templates bind against one `self` as usual.
// DOES NOT OWN: the ranking algorithm itself (filamentdb-search.js), the
//     weight computation (server-side only, weights.py -- each library
//     row already carries the `weightText`/`weightPercent` api.py
//     computed, this file just renders it), or the library cache/sidebar
//     rows it reads (`self.library`, `self.toolLabel`, `self.toolForSpool`,
//     `self.loadLibrary`, `self.libraryLoaded` -- all set up by
//     filamentdb.js before calling attach()).

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

        self.pickerLocations = ko.pureComputed(function () {
            var seen = {};
            self.library().forEach(function (row) {
                if (row.locationId) {
                    seen[row.locationId] = true;
                }
            });
            return Object.keys(seen).sort();
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
                    // client-side arithmetic here.
                    weightText: row.weightText,
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
                            });
                        }
                    })
                    .fail(function (xhr) {
                        if (global.PNotify) {
                            new PNotify({
                                title: "Filament DB",
                                text:
                                    (xhr.responseJSON && xhr.responseJSON.error) ||
                                    "Could not assign spool",
                                type: "error",
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
