// Copyright (C) 2026 crzykidd
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// OWNS: the FilamentDBViewModel registration -- one Knockout viewmodel
//     bound to both the sidebar and settings panels.
// DOES NOT OWN: any actual spool/journal behaviour yet. This is the
//     skeleton the later steps (FR-2, FR-9b, ...) build on; it must bind
//     cleanly with zero console errors and nothing more.

$(function () {
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

        // Sidebar placeholder -- replaced by the live spool list in a
        // later step (FR-2). Present now purely to prove the binding
        // works end to end.
        self.placeholderText = ko.observable("No spools loaded");
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: FilamentDBViewModel,
        dependencies: ["settingsViewModel", "printerStateViewModel"],
        elements: ["#sidebar_plugin_filamentdb", "#settings_plugin_filamentdb"],
    });
});
