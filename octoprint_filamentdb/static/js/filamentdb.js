// Copyright (C) 2026 crzykidd
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// OWNS: the FilamentDBViewModel registration -- one Knockout viewmodel
//     bound to both the sidebar and settings panels -- and the live
//     raw-millimetre odometer readout (FR-5's UI instrument): receiving
//     `send_plugin_message` pushes and rendering per-tool totals.
// DOES NOT OWN: any spool/journal behaviour yet (FR-2, FR-9b, ...), nor
//     mm->gram conversion or any Filament DB data -- this step is
//     deliberately millimetres only (see
//     prompts/2026-08-02-live-mm-readout.md).

$(function () {
    // Stateless: formats a millimetre total as e.g. "4 062.3 mm"
    // (thousands-grouped, one decimal). Pure display formatting, so it
    // lives outside the viewmodel rather than as a method on it.
    function formatMillimetres(mm) {
        var rounded = Math.round((mm || 0) * 10) / 10;
        var fixed = rounded.toFixed(1);
        var parts = fixed.split(".");
        var grouped = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, " ");
        return grouped + "." + parts[1] + " mm";
    }

    function FilamentDBViewModel(parameters) {
        var self = this;

        self.settingsViewModel = parameters[0];
        self.printerState = parameters[1];

        // Deliberately NOT `self.settings = self.settingsViewModel.settings`
        // here. settingsViewModel.settings is `undefined` until its
        // requestData() call resolves, which happens in main.js's
        // fetchSettings() -- *after* every view model has already been
        // constructed. Caching it in the constructor freezes in that
        // `undefined` forever, since it's a plain property assignment, not
        // a live binding. Templates read `settingsViewModel.settings...`
        // directly instead, which is evaluated at bind time (after
        // fetchSettings' requestData().done()), by which point it holds
        // the real data.

        // Sidebar placeholder -- replaced by the live spool list in a
        // later step (FR-2). Present now purely to prove the binding
        // works end to end.
        self.placeholderText = ko.observable("No spools loaded");

        // -- Live raw-millimetre odometer readout (this step) -----------
        //
        // `undefined`/not-yet-received until the first `send_plugin_message`
        // push arrives (i.e. until a print has started at least once since
        // this page loaded) -- so the idle state before any print simply
        // shows no odometer section at all, never a stale figure presented
        // as current.
        self.odometerPrinting = ko.observable(false);
        self.odometerRows = ko.observableArray([]);
        self.hasOdometerData = ko.pureComputed(function () {
            return self.odometerRows().length > 0;
        });

        self.onDataUpdaterPluginMessage = function (plugin, data) {
            if (plugin !== "filamentdb" || !data || data.type !== "odometer") {
                return;
            }

            // 1-based on screen by default (toolDisplayOffset, FR-3);
            // settingsViewModel.settings is only populated after
            // fetchSettings() resolves, same caveat as above, so guard
            // defensively rather than assuming it is ready.
            var offset = 1;
            var pluginSettings =
                self.settingsViewModel.settings &&
                self.settingsViewModel.settings.plugins &&
                self.settingsViewModel.settings.plugins.filamentdb;
            if (pluginSettings && pluginSettings.toolDisplayOffset) {
                var unwrapped = ko.utils.unwrapObservable(
                    pluginSettings.toolDisplayOffset
                );
                if (unwrapped !== undefined && unwrapped !== null) {
                    offset = unwrapped;
                }
            }

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
                        label: "Tool " + (toolIndex + offset),
                        mmText: formatMillimetres(totals[toolIndex]),
                    };
                });

            self.odometerPrinting(!!data.printing);
            self.odometerRows(rows);
        };
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: FilamentDBViewModel,
        dependencies: ["settingsViewModel", "printerStateViewModel"],
        elements: ["#sidebar_plugin_filamentdb", "#settings_plugin_filamentdb"],
    });
});
