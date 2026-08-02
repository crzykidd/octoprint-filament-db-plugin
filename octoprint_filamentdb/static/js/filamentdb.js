// Copyright (C) 2026 crzykidd
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// OWNS: the FilamentDBViewModel registration -- one Knockout viewmodel
//     bound to both the sidebar and settings panels -- plus: the live
//     raw-millimetre odometer readout (FR-5's UI instrument), Test
//     Connection (FR-1), loading/caching the spool library from
//     GET /api/plugin/filamentdb, the sidebar's per-tool rows (computed
//     net weight via FilamentDBWeights, C-2), clear/deep-link actions,
//     and tool numbering (count from the printer profile, 1-based
//     display). The picker modal itself is
//     `FilamentDBPicker.attach(self)`, called at the end of the
//     constructor -- split out to stay under the 500-line module cap
//     (PRD N-1); see that file's docstring.
// DOES NOT OWN: the search ranking algorithm (filamentdb-search.js), the
//     weight arithmetic itself (filamentdb-weights.js -- this file only
//     calls it), the picker modal's own state (filamentdb-picker.js), or
//     any server-side state (api.py, assignment.py, client/).

$(function () {
    // Stateless: formats a millimetre total as e.g. "4 062.3 mm"
    // (thousands-grouped, one decimal). Pure display formatting, so it
    // lives outside the viewmodel rather than as a method on it.
    function formatMillimetres(mm) {
        var rounded = Math.round((mm || 0) * 10) / 10;
        var fixed = rounded.toFixed(1);
        var parts = fixed.split(".");
        var grouped = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, " ");
        return grouped + "." + parts[1] + " mm";
    }

    function FilamentDBViewModel(parameters) {
        var self = this;

        self.settingsViewModel = parameters[0];
        self.printerState = parameters[1];
        self.printerProfiles = parameters[2];

        // Deliberately NOT `self.settings = self.settingsViewModel.settings`
        // here. settingsViewModel.settings is `undefined` until its
        // requestData() call resolves, which happens in main.js's
        // fetchSettings() -- *after* every view model has already been
        // constructed. Caching it in the constructor freezes in that
        // `undefined` forever, since it's a plain property assignment, not
        // a live binding. `pluginSettings()` re-reads on every call
        // instead, same rule templates follow by binding to
        // `settingsViewModel.settings...` directly.
        function pluginSettings() {
            var settings = self.settingsViewModel.settings;
            return settings && settings.plugins && settings.plugins.filamentdb;
        }

        // -- Live raw-millimetre odometer readout (FR-5 UI instrument) ---
        self.odometerPrinting = ko.observable(false);
        self.odometerRows = ko.observableArray([]);
        self.hasOdometerData = ko.pureComputed(function () {
            return self.odometerRows().length > 0;
        });

        // -- Tool count / numbering ---------------------------------
        // Straight from the printer profile -- the simple single-source
        // read. FR-3's full three-source union (profile + analysis
        // metadata + slicer block) is a later step; assigning a spool
        // needs only this.
        self.toolCount = ko.pureComputed(function () {
            // NOTE: `printerProfiles.currentProfile` is just the profile's
            // *id string* (see OctoPrint's own printerprofiles.js
            // fromResponse()) -- the actual data, including
            // extruder.count, lives on the separate `currentProfileData`
            // observable, a ko.mapping-wrapped object whose leaves
            // (including extruder.count) are themselves observables. Easy
            // to get wrong since both names look plausible; caught live
            // by driving the real "raise to 2 extruders" verification
            // step rather than by reading the source alone.
            var profile =
                self.printerProfiles &&
                self.printerProfiles.currentProfileData &&
                self.printerProfiles.currentProfileData();
            var count = profile && profile.extruder && profile.extruder.count;
            count = ko.utils.unwrapObservable(count);
            return count && count > 0 ? count : 1;
        });

        self.toolDisplayOffset = ko.pureComputed(function () {
            var settings = pluginSettings();
            var offset = settings && ko.utils.unwrapObservable(settings.toolDisplayOffset);
            return offset !== undefined && offset !== null ? offset : 1;
        });

        // Single extruder: follow OctoPrint's own convention and drop the
        // index entirely (PRD "Tool numbering").
        self.toolLabel = function (toolIndex) {
            if (self.toolCount() <= 1) {
                return "Tool";
            }
            return "Tool " + (toolIndex + self.toolDisplayOffset());
        };

        self.onDataUpdaterPluginMessage = function (plugin, data) {
            if (plugin !== "filamentdb" || !data) {
                return;
            }
            if (data.type === "odometer") {
                self._handleOdometerMessage(data);
            } else if (data.type === "assignment") {
                self.selectedSpools(data.selectedSpools || {});
            }
        };

        self._handleOdometerMessage = function (data) {
            var totals = data.totals || {};
            var rows = Object.keys(totals)
                .map(function (key) {
                    return parseInt(key, 10);
                })
                .sort(function (a, b) {
                    return a - b;
                })
                .map(function (toolIndex) {
                    return {
                        toolIndex: toolIndex,
                        label: self.toolLabel(toolIndex),
                        mmText: formatMillimetres(totals[toolIndex]),
                    };
                });

            self.odometerPrinting(!!data.printing);
            self.odometerRows(rows);
        };

        // -- FR-1: connect / Test Connection -----------------------------
        self.testingConnection = ko.observable(false);
        self.testConnectionResult = ko.observable(null);

        self.testConnection = function () {
            self.testingConnection(true);
            self.testConnectionResult(null);
            OctoPrint.simpleApiCommand("filamentdb", "test_connection")
                .done(function (response) {
                    self.testConnectionResult(response);
                })
                .fail(function (xhr) {
                    var message =
                        (xhr.responseJSON && xhr.responseJSON.error) || "Request failed";
                    self.testConnectionResult({ connected: false, error: message });
                })
                .always(function () {
                    self.testingConnection(false);
                });
        };

        // -- FR-2: spool library cache + current assignments -------------

        // Flattened rows built from GET /api/plugin/filamentdb -- one row
        // per spool, filament fields denormalised onto it so the picker's
        // client-side search/filter (no request per keystroke) has
        // everything in one place.
        self.library = ko.observableArray([]);
        self.libraryLoaded = ko.observable(false);
        self.libraryError = ko.observable(null);

        // Raw {"0": record, ...} straight from settings' selectedSpools
        // shape (FR-2), kept live by both the initial GET and every
        // `assignment` push (assignment.py's AssignmentStore._push()).
        self.selectedSpools = ko.observable({});

        self.loadLibrary = function () {
            return OctoPrint.simpleApiGet("filamentdb")
                .done(function (response) {
                    var rows = [];
                    (response.filaments || []).forEach(function (filament) {
                        (filament.spools || []).forEach(function (spool) {
                            rows.push({
                                filamentId: filament.id,
                                spoolId: spool.id,
                                id: spool.id,
                                instanceId: spool.instanceId,
                                label: spool.label,
                                vendor: filament.vendor,
                                name: filament.name,
                                type: filament.type,
                                color: filament.color,
                                // v1 has no /api/locations lookup (out of
                                // scope -- C-3b's field list carries the
                                // raw locationId only, not a resolved
                                // name). The location filter therefore
                                // filters and displays by id.
                                locationName: spool.locationId,
                                locationId: spool.locationId,
                                retired: !!spool.retired,
                                totalWeight: spool.totalWeight,
                                spoolWeight: filament.spoolWeight,
                                netFilamentWeight: filament.netFilamentWeight,
                                density: filament.density,
                            });
                        });
                    });
                    self.library(rows);
                    self.selectedSpools(response.selectedSpools || {});
                    self.libraryLoaded(true);
                    self.libraryError(null);
                })
                .fail(function (xhr) {
                    self.libraryError(
                        (xhr.responseJSON && xhr.responseJSON.error) ||
                            "Could not reach Filament DB"
                    );
                });
        };

        self.refreshLibrary = function () {
            OctoPrint.simpleApiCommand("filamentdb", "refresh").done(function () {
                self.loadLibrary();
            });
        };

        self.toolForSpool = function (spoolId) {
            var selected = self.selectedSpools() || {};
            for (var key in selected) {
                if (
                    Object.prototype.hasOwnProperty.call(selected, key) &&
                    selected[key] &&
                    selected[key].spoolId === spoolId
                ) {
                    return key;
                }
            }
            return null;
        };

        // -- Sidebar rows -- fixed four lines, computed weight (C-2) -----
        self.toolRows = ko.pureComputed(function () {
            var rows = [];
            var selected = self.selectedSpools() || {};
            var count = self.toolCount();
            for (var i = 0; i < count; i++) {
                var record = selected[String(i)];
                // Every key referenced by a bare (non-`if`-guarded)
                // binding in the sidebar template -- currently just the
                // swatch's `color` -- must exist on every row object even
                // when unassigned. Knockout evaluates a `data-bind`
                // expression as `with($data){ <expr> }`; if the property
                // is genuinely absent (not merely undefined) it falls
                // through to global scope and throws a ReferenceError
                // instead of resolving to `undefined` -- caught by the
                // Playwright console check (docs/decisions.md's
                // "UI work needs a real browser check" lesson, again).
                var row = {
                    toolIndex: i,
                    label: self.toolLabel(i),
                    assigned: !!record,
                    color: null,
                };
                if (record) {
                    var display = record.display || {};
                    var weight = FilamentDBWeights.compute(
                        display.totalWeight,
                        display.spoolWeight,
                        display.netFilamentWeight
                    );
                    row.vendor = display.vendor;
                    row.name = display.name;
                    row.type = display.type;
                    // The swatch is the one literal colour in this UI
                    // (PRD "Looking native"); null (a multi-colour
                    // filament with no single primary, e.g. #177) falls
                    // back to a neutral grey rather than throwing --
                    // matches Filament DB's own default for "no colour".
                    row.color = display.color || "#808080";
                    row.spoolLabel = display.label;
                    row.instanceId = record.instanceId;
                    row.weightText = weight.text;
                    row.hasBar = weight.percent !== null;
                    row.percentStyle = "width: " + (weight.percent || 0) + "%";
                    row.percentText =
                        weight.percent !== null ? Math.round(weight.percent) + "%" : "";
                    row.filamentId = record.filamentId;
                    row.spoolId = record.spoolId;
                    row.deepLink = self.filamentDbDeepLink(record.filamentId, record.spoolId);
                    row.hoverTitle =
                        "Gross " +
                        (display.totalWeight !== null && display.totalWeight !== undefined
                            ? FilamentDBWeights.trim(display.totalWeight) + " g"
                            : "unknown") +
                        " · Tare " +
                        (display.spoolWeight !== null && display.spoolWeight !== undefined
                            ? FilamentDBWeights.trim(display.spoolWeight) + " g"
                            : "not set");
                }
                rows.push(row);
            }
            return rows;
        });

        self.filamentDbUrl = ko.pureComputed(function () {
            var settings = pluginSettings();
            var url = settings && ko.utils.unwrapObservable(settings.filamentDbUrl);
            return url ? url.replace(/\/+$/, "") : "";
        });

        self.filamentDbDeepLink = function (filamentId, spoolId) {
            var base = self.filamentDbUrl();
            if (!base) {
                return null;
            }
            return base + "/filaments/" + filamentId + "?spool=" + spoolId;
        };

        self.openFilamentDb = function () {
            var base = self.filamentDbUrl();
            if (base) {
                window.open(base, "_blank");
            }
        };

        self.openSpoolInFilamentDb = function (row) {
            if (row.deepLink) {
                window.open(row.deepLink, "_blank");
            }
        };

        self.clearTool = function (row) {
            // selectedSpools updates via the `assignment` push -- nothing
            // else to do here.
            OctoPrint.simpleApiCommand("filamentdb", "clear", { toolIndex: row.toolIndex });
        };

        self.onStartupComplete = function () {
            self.loadLibrary();
        };

        // The picker modal's own state/behaviour -- see that file's
        // docstring for why it is split out.
        FilamentDBPicker.attach(self);
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: FilamentDBViewModel,
        dependencies: ["settingsViewModel", "printerStateViewModel", "printerProfilesViewModel"],
        elements: ["#sidebar_plugin_filamentdb", "#settings_plugin_filamentdb"],
    });
});
