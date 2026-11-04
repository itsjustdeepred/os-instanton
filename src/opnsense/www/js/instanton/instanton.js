/*
 * Instant On monitor - shared front-end code for the plugin pages.
 * Copyright (C) 2026 os-instanton contributors. BSD 2-Clause license.
 *
 * Every value that comes from a device (names, descriptions, log lines)
 * is escaped before it is inserted into the page.
 */
(function (window, $) {
    'use strict';

    var API = window.InstantOnApiBase || '/api/instanton/';
    var REFRESH_SECONDS = 30;

    // ------------------------------------------------------------------
    // formatting helpers
    // ------------------------------------------------------------------
    function esc(value) {
        if (value === null || value === undefined) {
            return '';
        }
        return String(value).replace(/[&<>"']/g, function (c) {
            return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
        });
    }

    function duration(seconds) {
        if (seconds === null || seconds === undefined || isNaN(seconds)) {
            return '';
        }
        seconds = Math.max(0, Math.floor(seconds));
        var d = Math.floor(seconds / 86400), h = Math.floor(seconds % 86400 / 3600),
            m = Math.floor(seconds % 3600 / 60), s = seconds % 60;
        if (d) { return d + 'd ' + h + 'h'; }
        if (h) { return h + 'h ' + m + 'm'; }
        if (m) { return m + 'm ' + s + 's'; }
        return s + 's';
    }

    function ago(ts) {
        if (!ts) {
            return '';
        }
        var diff = Date.now() / 1000 - ts;
        if (diff < 45) { return 'just now'; }
        return duration(diff) + ' ago';
    }

    function datetime(ts) {
        if (!ts) {
            return '';
        }
        var d = new Date(ts * 1000);
        var pad = function (n) { return n < 10 ? '0' + n : String(n); };
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' +
            pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
    }

    function bytes(n) {
        if (n === null || n === undefined) { return ''; }
        var units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'], i = 0;
        while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
        return (i ? n.toFixed(1) : n) + ' ' + units[i];
    }

    function bps(n) {
        if (n === null || n === undefined) { return '<span class="text-muted">-</span>'; }
        var units = ['b/s', 'kb/s', 'Mb/s', 'Gb/s'], i = 0;
        while (n >= 1000 && i < units.length - 1) { n /= 1000; i++; }
        return (i ? n.toFixed(1) : n) + ' ' + units[i];
    }

    function speed(mbps) {
        if (!mbps) { return ''; }
        return mbps >= 1000 ? (mbps / 1000) + ' Gb/s' : mbps + ' Mb/s';
    }

    function badge(text, kind, title) {
        return '<span class="label label-' + (kind || 'default') + '"' +
            (title ? ' title="' + esc(title) + '"' : '') + '>' + esc(text) + '</span>';
    }

    function levelBadge(level) {
        var map = {critical: 'danger', error: 'danger', emergency: 'danger', alert: 'danger',
                   warning: 'warning', notice: 'info', info: 'info', debug: 'default'};
        return badge(level, map[level] || 'default');
    }

    function onlineBadge(online, onText, offText) {
        return online ? badge(onText || 'online', 'success') : badge(offText || 'offline', 'danger');
    }

    function icon(name, title) {
        return '<i class="fa fa-fw fa-' + name + '"' + (title ? ' title="' + esc(title) + '"' : '') + '></i>';
    }

    // ------------------------------------------------------------------
    // data access
    // ------------------------------------------------------------------
    function api(path, method) {
        return $.ajax({url: API + path, type: method || 'GET', dataType: 'json', cache: false});
    }

    // ------------------------------------------------------------------
    // help panels
    // ------------------------------------------------------------------
    var HELP = {
        overview: '<p>Health of the Instant On network at a glance: switch, access points, clients and power over ' +
            'Ethernet, followed by the <b>checks</b> the plugin runs on every poll and the latest <b>events</b>.</p>' +
            '<ul><li><b>Checks</b> point at configuration or hardware problems (wrong clock, failing time sync, ' +
            'unstable ports, crashed access points, PoE faults). Each one explains what to look at.</li>' +
            '<li><b>Front panel</b>: green = connected at 1 Gb/s or more, amber = slower link, grey = no link, ' +
            'striped = disabled. ' + icon('bolt') + ' powers a device over PoE, ' + icon('wifi') +
            ' is an access point, ' + icon('arrow-up') + ' leads to the firewall. Hover a port for details, ' +
            'click it to open the port list.</li></ul>' +
            '<p>Data is read in the background by the monitor (see <a href="/ui/instanton/index/settings">Settings</a>). ' +
            'This page reloads every ' + REFRESH_SECONDS + ' seconds; <b>Refresh now</b> polls the devices immediately.</p>',
        switch: '<p>Everything the switch reports through its local web interface.</p>' +
            '<ul><li><b>Throughput</b> is the average since the previous poll; it appears after the second poll.</li>' +
            '<li><b>Flaps</b> counts link-down messages for the port in the switch log, ignoring moments when many ' +
            'ports dropped together (restart, firmware update). The switch keeps a few hundred log lines only.</li>' +
            '<li><b>Errors</b> are packet errors since the counters were last cleared: a growing number usually ' +
            'means a bad cable or connector.</li>' +
            '<li><b>Neighbour</b> comes from LLDP: devices that announce themselves (access points, other switches).</li>' +
            '<li><b>Role</b>: <i>ap</i> access point, <i>uplink</i> towards the firewall (its addresses are not listed ' +
            'as clients), <i>switch</i> another switch, <i>device</i> anything else.</li></ul>' +
            '<p><b>Changes</b>: when <i>Allow changes</i> is on in Settings, the ' + icon('pencil') + ' button at the end of ' +
            'each port row edits the description, switches the port or its PoE power on and off, power-cycles the connected ' +
            'device and starts a cable test. The port that leads to the firewall cannot be switched off. Every change is ' +
            'saved on the switch (unless disabled in Settings) and listed under Events. More settings are on the ' +
            '<a href="/ui/instanton/index/configuration">Configuration</a> page.</p>' +
            '<p><b>Time server</b>: <i>no answer</i> means the switch asks the server for the time but gets no reply; when the ' +
            'server is this firewall, check that a rule on the switch network allows UDP port 123 to the firewall.</p>',
        accesspoints: '<p>Access points are found through the switch (LLDP) or added by address in Settings. Each one ' +
            'publishes a diagnostic page on port 8080 that the plugin reads without a password.</p>' +
            '<ul><li><b>Coordinator</b>: the access point that manages the others (the "swarm" master).</li>' +
            '<li><b>Last restart</b>: <i>Power-reset</i> is a normal power cycle; <i>Panic</i> or <i>assert</i> means ' +
            'the firmware crashed. Repeated crashes are worth reporting to HPE support or updating the firmware.</li>' +
            '<li><b>Time</b>: access points try NTP once while starting, often before their network is up, and then take ' +
            'the time from the Instant On cloud. The plugin compares their clock with the firewall: <i>correct</i> is fine even ' +
            'when the access point itself reports an NTP error.</li>' +
            '<li><b>Clients</b> counts devices seen on the switch port of the access point. Clients of a meshed access ' +
            'point are counted on the access point it is meshed to.</li></ul>' +
            '<p>Radio channels, SSIDs and signal levels are only known to the Instant On cloud: enable the cloud source ' +
            'in Settings to see them. Access points cannot be changed from here: they take their settings from the Instant On ' +
            'app or portal and offer no local configuration interface. Their PoE port can be power-cycled from the Switch page.</p>',
        clients: '<p>Every device the switch has learned, enriched with the IP address and name the firewall knows ' +
            '(ARP table, DHCP leases and static mappings).</p>' +
            '<ul><li><b>Wireless</b> devices are those learned on an access point port. Without the cloud source the ' +
            'plugin cannot tell which SSID or band they use.</li>' +
            '<li><b>Private MAC</b>: phones and laptops use a random address per network, so the vendor is unknown and ' +
            'the same device may appear again with a new address after a reset of its network settings.</li>' +
            '<li><b>Offline</b> devices are kept for the history period set in Settings.</li>' +
            '<li>Devices without an IP are usually on a VLAN the firewall does not route, use a static address, or ' +
            'have been quiet for a while.</li></ul>',
        configuration: '<p>The configuration of the switch, read from its local web interface and grouped like its menus. ' +
            'Sections are read when a tab is opened; <b>Read from switch</b> refreshes the tab, <b>Read everything</b> ' +
            'loads all sections (about 30 seconds).</p>' +
            '<ul><li>The <b>System</b> tab starts with the common tasks: name, time and time server, remote syslog, saving the ' +
            'configuration, the locator LED and restarting the switch.</li>' +
            '<li>Other sections show the values as the switch stores them. Most switches use <i>1</i> for on and <i>2</i> ' +
            'for off; such fields are shown as a choice. Field names are those of the switch interface.</li>' +
            '<li>' + badge('caution', 'warning') + ' sections can interrupt traffic (VLANs, spanning tree, link ' +
            'aggregation, filtering, QoS, port settings): you are asked to confirm each change.</li>' +
            '<li>' + badge('read-only', 'danger') + ' sections control access to the switch (management address and VLAN, ' +
            'accounts and passwords, login authentication, web service, certificates, firmware, access lists). They are ' +
            'never changed by the plugin, so a mistake cannot lock the firewall out of the switch.</li>' +
            '<li>Rows of the port that leads to the firewall are protected in every section.</li></ul>' +
            '<p>Each change is checked, sent to the switch, saved to its startup configuration (see Settings) and recorded ' +
            'under <a href="/ui/instanton/index/events">Events</a>. Editing needs <b>Allow changes</b> in ' +
            '<a href="/ui/instanton/index/settings">Settings</a> and an administrator account on the switch.</p>',
        events: '<p>Changes detected between two polls: ports going up or down, access points going offline or ' +
            'restarting, firmware changes, new devices on the network, PoE faults and polling errors, plus every ' +
            'configuration change made from the plugin (area <i>change</i>). The same events ' +
            'are written to the system log (<a href="/ui/diagnostics/log/core/instanton">Log File</a>), so they can be ' +
            'forwarded to a remote syslog server or used for notifications.</p>',
        settings: '<p>By default the plugin only <b>reads</b>. Tick <b>Allow changes</b> to manage the switch from the Switch ' +
            'and Configuration pages; management access, accounts, firmware and the port towards the firewall stay protected.</p>' +
            '<ol><li>Enter the switch address and an account of its web interface.</li>' +
            '<li>Keep <i>Discover through the switch</i> on; add meshed access points by address.</li>' +
            '<li>Press <b>Test connection</b>, then tick <b>Enable monitor</b> and <b>Apply</b>.</li></ol>' +
            '<p>Press the <i>full help</i> switch on the top right of the form to show the explanation of every field, ' +
            'and <i>advanced mode</i> to show the less common options.</p>'
    };

    function helpPanel(page) {
        var key = 'instanton.help.' + page;
        var seen = null;
        try { seen = window.localStorage.getItem(key); } catch (e) { seen = null; }
        var open = seen === null || seen === 'open';
        var $panel = $('<div class="panel panel-default instanton-help">' +
            '<div class="panel-heading" role="button" tabindex="0">' + icon('question-circle') +
            ' About this page <i class="fa fa-chevron-down pull-right"></i></div>' +
            '<div class="panel-body">' + (HELP[page] || '') + '</div></div>');
        var $body = $panel.find('.panel-body');
        var $chev = $panel.find('.fa-chevron-down');
        function apply(state, store) {
            $body.toggle(state);
            $chev.toggleClass('fa-chevron-up', state).toggleClass('fa-chevron-down', !state);
            if (store) {
                try { window.localStorage.setItem(key, state ? 'open' : 'closed'); } catch (e) { /* ignore */ }
            }
        }
        $panel.find('.panel-heading').on('click keypress', function () {
            apply(!$body.is(':visible'), true);
        });
        apply(open, false);
        if (seen === null) {
            try { window.localStorage.setItem(key, 'closed'); } catch (e) { /* ignore */ }
        }
        return $panel;
    }

    // ------------------------------------------------------------------
    // toolbar: freshness, refresh, auto-refresh
    // ------------------------------------------------------------------
    function toolbar(onReload) {
        var $bar = $('<div class="instanton-toolbar">' +
            '<span class="instanton-age text-muted"></span> ' +
            '<label class="instanton-auto"><input type="checkbox" checked> auto-update</label> ' +
            '<button class="btn btn-default btn-xs instanton-refresh" type="button" ' +
            'title="Poll the switch and the access points now">' + icon('refresh') + ' Refresh now</button></div>');
        var timer = null;
        function schedule() {
            clearInterval(timer);
            if ($bar.find('input').is(':checked')) {
                timer = setInterval(onReload, REFRESH_SECONDS * 1000);
            }
        }
        $bar.find('input').on('change', schedule);
        $bar.find('.instanton-refresh').on('click', function () {
            var $btn = $(this);
            $btn.prop('disabled', true).find('i').addClass('fa-spin');
            api('service/refresh', 'POST').always(function () {
                $btn.prop('disabled', false).find('i').removeClass('fa-spin');
                onReload();
            });
        });
        schedule();
        return $bar;
    }

    function updateAge($root, meta) {
        var $age = $root.find('.instanton-age');
        if (!meta || !meta.generated) {
            $age.text('');
            return;
        }
        $age.text('Data from ' + ago(meta.generated) + ' (' + datetime(meta.generated) + ')');
    }

    function statusBanner(meta, error) {
        if (error) {
            return '<div class="alert alert-danger">' + icon('exclamation-triangle') + ' ' + esc(error) + '</div>';
        }
        if (!meta || !meta.configured) {
            return '<div class="alert alert-info">' + icon('info-circle') + ' The plugin is not configured yet. ' +
                'Open <a href="/ui/instanton/index/settings">Settings</a> to connect the switch.</div>';
        }
        if (!meta.generated) {
            return '<div class="alert alert-info">' + icon('info-circle') + ' No data collected yet. ' +
                (meta.enabled ? 'The first poll is running; press <b>Refresh now</b> or wait a moment.'
                    : 'The monitor is disabled: enable it in <a href="/ui/instanton/index/settings">Settings</a> ' +
                      'or press <b>Refresh now</b> for a single poll.') + '</div>';
        }
        var html = '';
        if (!meta.enabled) {
            html += '<div class="alert alert-warning">' + icon('pause-circle') + ' The background monitor is ' +
                'disabled, so this data is not updated automatically. Enable it in ' +
                '<a href="/ui/instanton/index/settings">Settings</a>.</div>';
        } else if (meta.age > Math.max(180, meta.interval * 3)) {
            html += '<div class="alert alert-warning">' + icon('clock-o') + ' The data is ' + duration(meta.age) +
                ' old: the monitor may have stopped. Check the service status in Settings and the ' +
                '<a href="/ui/diagnostics/log/core/instanton">log</a>.</div>';
        }
        $.each(meta.sources || {}, function (name, src) {
            if (src.enabled && !src.ok && src.error) {
                html += '<div class="alert alert-danger">' + icon('plug') + ' <b>' + esc(name) +
                    '</b>: ' + esc(src.error) + '</div>';
            }
        });
        return html;
    }

    // ------------------------------------------------------------------
    // generic table with search, sorting and filters
    // ------------------------------------------------------------------
    function Table($target, options) {
        this.$target = $target;
        this.columns = options.columns;
        this.rows = [];
        this.sortKey = options.sortKey || null;
        this.sortDir = options.sortDir || 1;
        this.filter = '';
        this.extraFilter = options.extraFilter || null;
        this.emptyText = options.emptyText || 'Nothing to show.';
        this.rowClass = options.rowClass || null;
        this.searchable = options.search !== false;
        this.id = options.id || '';
        this.build();
    }

    Table.prototype.build = function () {
        var self = this;
        var head = '<tr>' + $.map(this.columns, function (c, i) {
            return '<th data-col="' + i + '" class="' + (c.cls || '') + (c.sort !== false ? ' sortable' : '') + '"' +
                (c.title ? ' title="' + esc(c.title) + '"' : '') + '>' + esc(c.label) +
                (c.title ? ' <i class="fa fa-info-circle text-muted"></i>' : '') + ' <i class="sort-icon"></i></th>';
        }).join('') + '</tr>';
        this.$wrap = $('<div class="instanton-table">' +
            (this.searchable ? '<div class="instanton-table-tools"><input type="search" class="form-control input-sm" ' +
                'placeholder="Search..." aria-label="Search"><span class="instanton-count text-muted"></span></div>' : '') +
            '<div class="table-responsive"><table class="table table-striped table-condensed table-hover">' +
            '<thead>' + head + '</thead><tbody></tbody></table></div></div>');
        this.$target.empty().append(this.$wrap);
        this.$wrap.find('input[type=search]').on('input', function () {
            self.filter = $(this).val().toLowerCase();
            self.render();
        });
        this.$wrap.find('th.sortable').on('click', function () {
            var key = parseInt($(this).data('col'), 10);
            if (self.sortKey === key) {
                self.sortDir = -self.sortDir;
            } else {
                self.sortKey = key;
                self.sortDir = 1;
            }
            self.render();
        });
    };

    Table.prototype.setRows = function (rows) {
        this.rows = rows || [];
        this.render();
    };

    Table.prototype.visibleRows = function () {
        var self = this;
        var rows = this.rows.filter(function (r) {
            if (self.extraFilter && !self.extraFilter(r)) {
                return false;
            }
            if (!self.filter) {
                return true;
            }
            return $.map(self.columns, function (c) {
                return c.text ? c.text(r) : (c.key ? r[c.key] : '');
            }).join(' ').toLowerCase().indexOf(self.filter) !== -1;
        });
        if (this.sortKey !== null && this.columns[this.sortKey]) {
            var col = this.columns[this.sortKey], dir = this.sortDir;
            var val = col.sortValue || function (r) { return col.text ? col.text(r) : r[col.key]; };
            rows = rows.slice().sort(function (a, b) {
                var x = val(a), y = val(b);
                if (x === y) { return 0; }
                if (x === null || x === undefined || x === '') { return 1; }
                if (y === null || y === undefined || y === '') { return -1; }
                if (typeof x === 'number' && typeof y === 'number') { return (x - y) * dir; }
                return String(x).localeCompare(String(y), undefined, {numeric: true}) * dir;
            });
        }
        return rows;
    };

    Table.prototype.render = function () {
        var self = this;
        var rows = this.visibleRows();
        var html = rows.length ? $.map(rows, function (r) {
            var cls = self.rowClass ? self.rowClass(r) : '';
            return '<tr' + (cls ? ' class="' + cls + '"' : '') + '>' + $.map(self.columns, function (c) {
                var v = c.render ? c.render(r) : esc(c.key ? r[c.key] : '');
                return '<td class="' + (c.cls || '') + '">' + (v === undefined || v === null ? '' : v) + '</td>';
            }).join('') + '</tr>';
        }).join('') : '<tr><td colspan="' + this.columns.length + '" class="text-center text-muted">' +
            esc(this.rows.length ? 'No match for the current filter.' : this.emptyText) + '</td></tr>';
        this.$wrap.find('tbody').html(html);
        this.$wrap.find('th .sort-icon').attr('class', 'sort-icon');
        if (this.sortKey !== null) {
            this.$wrap.find('th[data-col=' + this.sortKey + '] .sort-icon')
                .attr('class', 'sort-icon fa fa-sort-' + (this.sortDir > 0 ? 'asc' : 'desc'));
        }
        this.$wrap.find('.instanton-count').text(
            rows.length === this.rows.length ? rows.length + ' entries' : rows.length + ' of ' + this.rows.length + ' entries');
    };

    Table.prototype.csv = function (filename) {
        var cols = this.columns.filter(function (c) { return c.csv !== false; });
        var lines = [$.map(cols, function (c) { return '"' + c.label.replace(/"/g, '""') + '"'; }).join(',')];
        $.each(this.visibleRows(), function (_, r) {
            lines.push($.map(cols, function (c) {
                var v = c.csvValue ? c.csvValue(r) : (c.text ? c.text(r) : (c.key ? r[c.key] : ''));
                return '"' + String(v === null || v === undefined ? '' : v).replace(/"/g, '""') + '"';
            }).join(','));
        });
        var blob = new Blob([lines.join('\r\n')], {type: 'text/csv'});
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
    };

    // ------------------------------------------------------------------
    // switch front panel
    // ------------------------------------------------------------------
    function portTooltip(p) {
        var lines = [p.name + (p.description ? ' - ' + p.description : '')];
        if (!p.enabled) {
            lines.push('Disabled');
        } else if (p.up) {
            lines.push('Up, ' + speed(p.speed) + ' ' + p.duplex + ' duplex');
            if (p.rx_bps !== null && p.rx_bps !== undefined) {
                lines.push('In ' + $('<div>').html(bps(p.rx_bps)).text() + ', out ' + $('<div>').html(bps(p.tx_bps)).text());
            }
        } else {
            lines.push('No link');
        }
        if (p.neighbor && p.neighbor.name) { lines.push('Neighbour: ' + p.neighbor.name); }
        if (p.poe && p.poe.power_w) { lines.push('PoE ' + p.poe.power_w + ' W'); }
        if (p.mac_count) { lines.push(p.mac_count + ' MAC address' + (p.mac_count > 1 ? 'es' : '')); }
        if (p.pvid) { lines.push('VLAN ' + p.pvid + (p.tagged ? ', tagged ' + p.tagged : '')); }
        if (p.errors) { lines.push(p.errors + ' errors'); }
        if (p.flaps) { lines.push(p.flaps + ' link drops in the switch log'); }
        return lines.join('\n');
    }

    function frontPanel(ports) {
        if (!ports || !ports.length) {
            return '<p class="text-muted">No port data.</p>';
        }
        var copper = [], extra = [];
        $.each(ports, function (_, p) {
            (p.media === 'fiber' || p.speed >= 10000 || p.id > 48 ? extra : copper).push(p);
        });
        if (copper.length <= 8) { copper = ports; extra = []; }
        function cell(p) {
            var cls = 'port';
            if (!p.enabled) { cls += ' port-disabled'; }
            else if (!p.up) { cls += ' port-down'; }
            else if (p.speed >= 1000) { cls += ' port-up'; }
            else { cls += ' port-slow'; }
            if (p.errors || p.flaps >= 5) { cls += ' port-alert'; }
            var marks = '';
            if (p.role === 'ap') { marks += icon('wifi'); }
            else if (p.role === 'uplink') { marks += icon('arrow-up'); }
            else if (p.role === 'switch') { marks += icon('sitemap'); }
            if (p.poe && p.poe.status === 'delivering') { marks += icon('bolt'); }
            return '<a class="' + cls + '" href="/ui/instanton/index/switch#port-' + esc(p.name) + '" title="' +
                esc(portTooltip(p)) + '" data-port="' + esc(p.name) + '"><span class="port-num">' +
                esc(p.name.split('/').pop()) + '</span><span class="port-marks">' + marks + '</span></a>';
        }
        var top = [], bottom = [];
        $.each(copper, function (i, p) { (i % 2 === 0 ? top : bottom).push(cell(p)); });
        var html = '<div class="instanton-panel"><div class="panel-block"><div class="panel-row">' + top.join('') +
            '</div><div class="panel-row">' + bottom.join('') + '</div></div>';
        if (extra.length) {
            html += '<div class="panel-block panel-extra"><div class="panel-row">' + $.map(extra, cell).join('') + '</div></div>';
        }
        html += '</div><div class="instanton-legend text-muted small">' +
            '<span class="port port-up"></span> 1 Gb/s+ <span class="port port-slow"></span> slower ' +
            '<span class="port port-down"></span> no link <span class="port port-disabled"></span> disabled ' +
            '<span class="port port-up port-alert"></span> errors or unstable &nbsp; ' +
            icon('wifi') + ' access point ' + icon('arrow-up') + ' uplink ' + icon('sitemap') + ' switch ' +
            icon('bolt') + ' PoE</div>';
        return html;
    }

    // ------------------------------------------------------------------
    // page scaffolding
    // ------------------------------------------------------------------
    function Page(name, $root) {
        this.name = name;
        this.$root = $root;
        $root.addClass('instanton-page');
        this.$bar = toolbar(this.reload.bind(this));
        this.$banner = $('<div class="instanton-banner"></div>');
        this.$content = $('<div class="instanton-content"></div>');
        $root.empty().append(this.$bar, helpPanel(name), this.$banner, this.$content);
    }

    Page.prototype.reload = function () {
        var self = this;
        if (!this.loader) {
            return;
        }
        this.loader().done(function (data) {
            data = data || {};
            if (!self.noMeta) {
                self.$banner.html(statusBanner(data.meta, data.error));
                updateAge(self.$bar, data.meta);
            }
            self.render(data);
        }).fail(function (xhr) {
            self.$banner.html(statusBanner(null, 'Cannot load data (HTTP ' + xhr.status + ').'));
        });
    };

    function section(title, body, extraHeader) {
        return '<div class="content-box instanton-section"><div class="instanton-section-head"><h3>' + esc(title) +
            '</h3>' + (extraHeader || '') + '</div><div class="instanton-section-body">' + body + '</div></div>';
    }

    function kv(rows) {
        return '<table class="table table-condensed instanton-kv"><tbody>' + $.map(rows, function (r) {
            if (r[1] === null || r[1] === undefined || r[1] === '') { return ''; }
            return '<tr><th' + (r[2] ? ' title="' + esc(r[2]) + '"' : '') + '>' + esc(r[0]) + '</th><td>' + r[1] + '</td></tr>';
        }).join('') + '</tbody></table>';
    }

    // ------------------------------------------------------------------
    // pages
    // ------------------------------------------------------------------
    function insightList(items) {
        if (!items || !items.length) {
            return '<p class="text-success">' + icon('check-circle') + ' No problems found.</p>';
        }
        var cls = {critical: 'danger', warning: 'warning', info: 'info'};
        var ic = {critical: 'times-circle', warning: 'exclamation-triangle', info: 'info-circle'};
        return '<ul class="list-unstyled instanton-insights">' + $.map(items, function (i) {
            return '<li class="text-' + (cls[i.level] || 'muted') + '">' + icon(ic[i.level] || 'circle') +
                ' <b>' + esc(i.title) + '</b> <span class="text-muted small">[' + esc(i.area) + ']</span>' +
                '<div class="instanton-insight-detail">' + esc(i.detail) + '</div></li>';
        }).join('') + '</ul>';
    }

    function eventList(events) {
        if (!events || !events.length) {
            return '<p class="text-muted">No events recorded yet. Changes appear here from the second poll on.</p>';
        }
        return '<table class="table table-condensed"><tbody>' + $.map(events, function (e) {
            return '<tr><td class="text-nowrap text-muted" title="' + esc(datetime(e.time)) + '">' + esc(ago(e.time)) +
                '</td><td>' + levelBadge(e.level) + '</td><td>' + esc(e.message) + '</td></tr>';
        }).join('') + '</tbody></table><a href="/ui/instanton/index/events">All events &raquo;</a>';
    }

    function card(iconName, title, value, sub, kind, href) {
        return '<div class="col-xs-12 col-sm-6 col-md-3"><a class="instanton-card ' + (kind || '') + '" href="' + href +
            '">' + '<div class="instanton-card-icon">' + icon(iconName) + '</div><div class="instanton-card-body">' +
            '<div class="instanton-card-title">' + esc(title) + '</div><div class="instanton-card-value">' + value +
            '</div><div class="instanton-card-sub">' + sub + '</div></div></a></div>';
    }

    function overview($root) {
        var page = new Page('overview', $root);
        page.loader = function () { return api('status/summary'); };
        var ports = [];
        page.render = function (data) {
            var s = data.summary || {}, sw = data.switch || {};
            if (!data.meta || !data.meta.generated) { page.$content.empty(); return; }
            var cards = '<div class="row instanton-cards">' +
                card('server', 'Switch', s.switch_online ? s.ports_up + ' / ' + s.ports_total : 'offline',
                    s.switch_online ? 'ports connected' + (sw.temperature ? ' &middot; ' + esc(sw.temperature) + ' &deg;C' : '')
                        : esc(sw.error || ''), s.switch_online ? 'ok' : 'bad', '/ui/instanton/index/switch') +
                card('wifi', 'Access points', s.aps_online + ' / ' + s.aps_total, 'online' +
                    (data.swarm_size ? ' &middot; swarm of ' + esc(data.swarm_size) : ''),
                    s.aps_total && s.aps_online < s.aps_total ? 'bad' : 'ok', '/ui/instanton/index/accesspoints') +
                card('laptop', 'Clients', esc(s.clients_online), esc(s.clients_wireless) + ' wireless &middot; ' +
                    esc(s.clients_wired) + ' wired', 'ok', '/ui/instanton/index/clients') +
                card('bolt', 'Power over Ethernet', s.poe_w !== null && s.poe_w !== undefined ? esc(s.poe_w) + ' W' : '-',
                    s.poe_percent !== null && s.poe_percent !== undefined ? esc(s.poe_percent) + '% of ' +
                        esc((sw.poe || {}).nominal_w) + ' W budget' : '', 'ok', '/ui/instanton/index/switch#poe') +
                '</div>';
            var warn = s.warnings ? ' <span class="badge" title="Warnings and critical problems">' + esc(s.warnings) + '</span>' : '';
            page.$content.html(cards +
                '<div class="row"><div class="col-md-7">' + section('Checks', insightList(data.insights), warn) +
                '</div><div class="col-md-5">' + section('Recent events', eventList(data.events)) + '</div></div>' +
                '<div id="instanton-panel-holder"></div>' +
                section('Access points', '<div id="instanton-ap-mini"></div>'));
            api('status/ports').done(function (pd) {
                ports = pd.ports || [];
                $('#instanton-panel-holder').html(section('Front panel' + (sw.name ? ' - ' + sw.name : ''), frontPanel(ports)));
            });
            var t = new Table($('#instanton-ap-mini'), {search: false, sortKey: 0, columns: apColumns(true),
                emptyText: 'No access points found.'});
            t.setRows(data.aps || []);
        };
        page.reload();
    }

    function apColumns(compact) {
        var cols = [
            {label: 'Name', key: 'name', render: function (a) {
                return esc(a.name) + (a.master ? ' ' + badge('coordinator', 'primary',
                    'Manages the other access points of the swarm') : '');
            }},
            {label: 'Status', sortValue: function (a) { return a.online ? 1 : 0; }, text: function (a) { return a.online ? 'online' : 'offline'; },
                render: function (a) { return onlineBadge(a.online) + (a.error ? '<div class="small text-danger">' + esc(a.error) + '</div>' : ''); }},
            {label: 'Model', key: 'model'},
            {label: 'IP address', key: 'host', render: function (a) {
                return /^[\d.]+$/.test(a.host) ? '<a href="http://' + esc(a.host) + ':8080/" target="_blank" rel="noopener" ' +
                    'title="Open the diagnostic page">' + esc(a.host) + '</a>' : esc(a.host);
            }},
            {label: 'Uplink', title: 'Switch port, link speed and PoE draw', text: function (a) { return a.port || 'mesh'; },
                render: function (a) {
                    if (!a.port) { return '<span class="text-muted" title="' + esc(a.uplink || '') + '">mesh / other switch</span>'; }
                    return '<a href="/ui/instanton/index/switch#port-' + esc(a.port) + '">' + esc(a.port) + '</a> &middot; ' +
                        esc(speed(a.speed)) + (a.poe_w ? ' &middot; ' + esc(a.poe_w) + ' W' : '');
                }},
            {label: 'Clients', title: 'Devices learned on the switch port of this access point', key: 'clients',
                sortValue: function (a) { return a.clients || 0; }},
            {label: 'Firmware', key: 'firmware'}
        ];
        if (!compact) {
            cols.push(
                {label: 'Serial', key: 'serial'},
                {label: 'Cloud', key: 'cloud_status', render: function (a) {
                    if (!a.cloud_status) { return ''; }
                    return a.cloud_status === 'CONNECTED' ? badge('connected', 'success') : badge(a.cloud_status, 'warning', a.cloud_reason);
                }},
                {label: 'Time', title: 'Clock of the access point compared with the firewall, and where it got the time',
                    key: 'clock_skew', render: function (a) {
                    var src = a.time_source ? ' <span class="small text-muted">' + esc(a.time_source.toLowerCase()) + '</span>' : '';
                    if (a.clock_skew === null || a.clock_skew === undefined) { return a.ntp_status ? esc(a.ntp_status) : ''; }
                    if (Math.abs(a.clock_skew) > 300) {
                        return badge('off by ' + duration(Math.abs(a.clock_skew)), 'warning', 'NTP ' + (a.ntp_status || '') + ', server ' + (a.ntp_server || '?')) + src;
                    }
                    return badge('correct', 'success', 'NTP status ' + (a.ntp_status || '?') + (a.ntp_log ? ': ' + a.ntp_log : '')) + src;
                }},
                {label: 'Last restart', key: 'reboot_cause', render: function (a) {
                    return a.crashed ? '<span class="text-danger">' + icon('bug') + ' ' + esc(a.reboot_cause) + '</span>' : esc(a.reboot_cause);
                }}
            );
        }
        return cols;
    }

    var latestPorts = [];

    function switchPage($root) {
        var page = new Page('switch', $root);
        page.loader = function () { return api('status/switch'); };
        var portTable, logTable, vlanTable;
        page.render = function (data) {
            var sw = data.switch || {};
            if (!sw.host && !(data.meta || {}).generated) { page.$content.empty(); return; }
            if (!sw.online) {
                page.$content.html(section('Switch', '<p class="text-danger">' + icon('plug') + ' The switch could not be read: ' +
                    esc(sw.error || 'unknown error') + '</p>'));
                return;
            }
            canChange = !!(data.meta || {}).allow_changes;
            latestPorts = sw.ports || [];
            if (!portTable) {
                var fans = $.map(sw.fans || [], function (f) { return 'fan ' + f.id + ': ' + f.status; }).join(', ');
                page.$content.html(
                    '<div class="row"><div class="col-md-6" id="instanton-sw-info"></div><div class="col-md-6" id="instanton-sw-health"></div></div>' +
                    '<div id="instanton-sw-panel"></div>' +
                    section('Ports', '<div id="instanton-ports"></div>', '<a id="poe"></a><label class="instanton-auto small" ' +
                        'style="margin-left:auto;font-weight:normal"><input type="checkbox" id="instanton-only-up" checked> only ports with a link</label>') +
                    '<div class="row"><div class="col-md-4">' + section('VLANs', '<div id="instanton-vlans"></div>') +
                    '</div><div class="col-md-8">' + section('Switch log', '<div class="form-inline instanton-log-tools">' +
                        '<select class="form-control input-sm" id="instanton-log-level"><option value="">all levels</option>' +
                        '<option value="warning">warning and worse</option><option value="error">error and worse</option></select></div>' +
                        '<div id="instanton-log"></div>') + '</div></div>');
                portTable = new Table($('#instanton-ports'), {sortKey: 0, columns: portColumns(), id: 'ports',
                    extraFilter: function (p) {
                        return !$('#instanton-only-up').is(':checked') || p.up || window.location.hash === '#port-' + p.name;
                    },
                    rowClass: function (p) { return (!p.up ? 'instanton-dim' : '') + ' port-row-' + p.name.replace('/', '-'); }});
                vlanTable = new Table($('#instanton-vlans'), {search: false, sortKey: 0, columns: [
                    {label: 'ID', key: 'id', sortValue: function (v) { return v.id; }},
                    {label: 'Name', key: 'name'},
                    {label: 'Ports', title: 'Ports carrying this VLAN (untagged U, tagged T)', key: 'ports', sort: false}
                ]});
                var rank = {emergency: 0, alert: 1, critical: 2, error: 3, warning: 4, notice: 5, info: 6, debug: 7};
                logTable = new Table($('#instanton-log'), {columns: [
                    {label: 'Switch time', title: 'Time according to the switch clock', key: 'time_raw',
                        sortValue: function (l) { return l.time || 0; }, text: function (l) { return datetime(l.time) || l.time_raw; }},
                    {label: 'Level', key: 'severity', render: function (l) { return levelBadge(l.severity); }},
                    {label: 'Message', key: 'message'}
                ], extraFilter: function (l) {
                    var lvl = $('#instanton-log-level').val();
                    return !lvl || rank[l.severity] <= rank[lvl];
                }});
                $('#instanton-log-level').on('change', function () { logTable.render(); });
                $('#instanton-only-up').on('change', function () { portTable.render(); });
                $('#instanton-ports').on('click', '.instanton-port-edit', function () {
                    var name = $(this).data('port');
                    var p = $.grep(latestPorts, function (x) { return x.name === name; })[0];
                    if (p) {
                        portDialog(p, page.$banner, function () {
                            api('service/refresh', 'POST').always(function () { page.reload(); });
                        });
                    }
                });
                void fans;
            }
            var uptime = duration(sw.uptime);
            $('#instanton-sw-info').html(section('Device', kv([
                ['Name', esc(sw.name)], ['Model', esc(sw.model)], ['Serial number', esc(sw.serial)],
                ['MAC address', esc(sw.mac)], ['Firmware', esc(sw.firmware) + (sw.firmware_date ? ' <span class="text-muted small">(' + esc(sw.firmware_date) + ')</span>' : '')],
                ['Boot loader', esc(sw.boot_version)], ['Address', '<a href="https://' + esc(sw.host) + '/" target="_blank" rel="noopener">' + esc(sw.host) + '</a>'],
                ['Location', esc(sw.location)], ['Modules', $.map(sw.modules || [], function (m) { return esc(m.port + ': ' + m.type); }).join('<br>')]
            ])));
            var skew = sw.clock_skew;
            $('#instanton-sw-health').html(section('Health', kv([
                ['Uptime', esc(uptime)],
                ['Temperature', sw.temperature !== null ? (sw.temperature_ok ? '' : icon('fire') + ' ') + esc(sw.temperature) + ' &deg;C' +
                    (sw.temperature_ok ? ' ' + badge('normal', 'success') : ' ' + badge('alarm', 'danger')) : ''],
                ['Fans', $.map(sw.fans || [], function (f) { return 'fan ' + f.id + ' ' + (f.status === 'ok' ? badge('ok', 'success') : badge(f.status, 'danger')); }).join(' ')],
                ['Power supply', sw.psu ? (sw.psu === 'ok' ? badge('ok', 'success') : badge(sw.psu, 'danger')) : ''],
                ['PoE budget', sw.poe ? esc(sw.poe.used_w) + ' W of ' + esc(sw.poe.nominal_w) + ' W (' + esc(sw.poe.percent) + '%)' +
                    '<div class="progress instanton-progress"><div class="progress-bar' + (sw.poe.percent > 80 ? ' progress-bar-warning' : '') +
                    '" style="width:' + Math.min(100, sw.poe.percent) + '%"></div></div>' : ''],
                ['Clock', skew === null || skew === undefined ? '' : (Math.abs(skew) > 300 ?
                    '<span class="text-warning">' + icon('clock-o') + ' off by ' + esc(duration(Math.abs(skew))) + '</span>' : badge('in sync', 'success'))
                    + ' <span class="text-muted small">' + esc((sw.timezone_name || '') + ' UTC' + (sw.timezone || '')) + '</span>',
                    'Difference between the switch clock and the firewall clock, and the time zone of the switch'],
                ['Time server', sntpStatus(sw), 'SNTP servers configured on the switch and whether they answer'],
                ['Configuration', sw.config_saved ? badge('saved', 'success') : badge('unsaved changes', 'warning')],
                ['Web sessions', $.map(sw.sessions || [], function (s) { return esc(s.user + ' from ' + s.address); }).join('<br>'), 'Users logged in to the switch web interface right now']
            ])));
            $('#instanton-sw-panel').html(section('Front panel', frontPanel(sw.ports)));
            portTable.setRows(sw.ports || []);
            var vlanPorts = {};
            $.each(sw.ports || [], function (_, p) {
                $.each(String(p.untagged || '').split(','), function (_, v) { if (v) { (vlanPorts[v] = vlanPorts[v] || []).push(p.name + 'U'); } });
                $.each(String(p.tagged || '').split(','), function (_, v) { if (v) { (vlanPorts[v] = vlanPorts[v] || []).push(p.name + 'T'); } });
            });
            vlanTable.setRows($.map(sw.vlans || [], function (v) {
                var list = vlanPorts[String(v.id)] || [];
                return {id: v.id, name: v.name, ports: list.length > 8 ? list.length + ' ports' : list.join(' ')};
            }));
            api('status/log').done(function (ld) { logTable.setRows(ld.log || []); });
            highlightHash();
        };
        page.reload();
    }

    function sntpStatus(sw) {
        var list = sw.sntp_list || [];
        if (!list.length) {
            return '<span class="text-warning">none</span>' + (sw.time_mode === 'manual' ? ' <span class="text-muted small">(manual clock)</span>' : '');
        }
        return $.map(list, function (s) {
            if (s.last_response) {
                return esc(s.address) + ' ' + badge('answering', 'success', 'Last answer ' + datetime(s.last_response));
            }
            return esc(s.address) + ' ' + badge('no answer', 'warning', 'The switch sends requests but the server never answered');
        }).join('<br>');
    }

    function highlightHash() {
        var m = /#port-(.+)$/.exec(window.location.hash);
        if (!m) { return; }
        var $row = $('.port-row-' + decodeURIComponent(m[1]).replace('/', '-'));
        if ($row.length && !$row.data('flashed')) {
            $row.data('flashed', true).addClass('instanton-flash');
            $('html, body').animate({scrollTop: $row.offset().top - 120}, 300);
        }
    }

    function portColumns() {
        var cols = [
            {label: 'Port', key: 'name', sortValue: function (p) { return p.id; }, render: function (p) {
                return '<a id="port-' + esc(p.name) + '"></a><b>' + esc(p.name) + '</b>';
            }},
            {label: 'Description', key: 'description'},
            {label: 'Link', title: 'Link state, speed and duplex', text: function (p) { return p.up ? 'up ' + speed(p.speed) : (p.enabled ? 'down' : 'disabled'); },
                sortValue: function (p) { return p.up ? p.speed : -1; },
                render: function (p) {
                    if (!p.enabled) { return badge('disabled', 'default'); }
                    if (!p.up) { return '<span class="text-muted">down</span>'; }
                    return badge(speed(p.speed), p.speed >= 1000 ? 'success' : 'warning', p.duplex + ' duplex') +
                        (p.link_since ? '<div class="small text-muted" title="Link up since ' + esc(datetime(p.link_since)) + '">' + esc(duration(Date.now() / 1000 - p.link_since)) + '</div>' : '');
                }},
            {label: 'Role', key: 'role', render: function (p) {
                var ic = {ap: 'wifi', uplink: 'arrow-up', 'switch': 'sitemap', device: 'desktop'};
                return p.role && p.role !== 'empty' ? icon(ic[p.role] || 'circle-o') + ' ' + esc(p.role) : '';
            }},
            {label: 'Neighbour', title: 'Device announced through LLDP', text: function (p) { return (p.neighbor || {}).name || ''; },
                render: function (p) {
                    var n = p.neighbor;
                    if (!n) { return ''; }
                    return '<span title="' + esc(n.description) + '">' + esc(n.name || n.chassis_id) + '</span>' +
                        (n.ip ? '<div class="small text-muted">' + esc(n.ip) + '</div>' : '');
                }},
            {label: 'VLAN', title: 'Untagged VLAN (PVID) and tagged VLANs', text: function (p) { return p.pvid + ' ' + p.tagged; },
                sortValue: function (p) { return p.pvid; },
                render: function (p) { return esc(p.pvid || '') + (p.tagged ? '<div class="small text-muted" title="tagged">+' + esc(p.tagged) + '</div>' : ''); }},
            {label: 'PoE', title: 'Power delivered to the connected device', text: function (p) { return p.poe ? p.poe.status : ''; },
                sortValue: function (p) { return p.poe ? p.poe.power_w : -1; },
                render: function (p) {
                    if (!p.poe) { return ''; }
                    if (p.poe.status === 'delivering') { return icon('bolt') + esc(p.poe.power_w) + ' W <span class="small text-muted">class ' + esc(p.poe['class']) + '</span>'; }
                    if (p.poe.status === 'fault') { return badge('fault', 'danger'); }
                    return p.up ? '<span class="text-muted small">' + esc(p.poe.status) + '</span>' : '';
                }},
            {label: 'In', title: 'Average received rate since the previous poll', sortValue: function (p) { return p.rx_bps || 0; },
                render: function (p) { return p.up ? bps(p.rx_bps) : ''; }, cls: 'text-right text-nowrap', csvValue: function (p) { return p.rx_bps; }},
            {label: 'Out', title: 'Average transmitted rate since the previous poll', sortValue: function (p) { return p.tx_bps || 0; },
                render: function (p) { return p.up ? bps(p.tx_bps) : ''; }, cls: 'text-right text-nowrap', csvValue: function (p) { return p.tx_bps; }},
            {label: 'Total', title: 'Bytes received / transmitted since the counters were cleared',
                sortValue: function (p) { return (p.rx_bytes || 0) + (p.tx_bytes || 0); },
                render: function (p) { return p.rx_bytes || p.tx_bytes ? '<span class="small">' + esc(bytes(p.rx_bytes)) + ' / ' + esc(bytes(p.tx_bytes)) + '</span>' : ''; },
                cls: 'text-nowrap'},
            {label: 'MACs', title: 'Addresses learned on this port; click to list them', key: 'mac_count',
                sortValue: function (p) { return p.mac_count; },
                render: function (p) { return p.mac_count ? '<a href="/ui/instanton/index/clients#port=' + esc(p.name) + '">' + esc(p.mac_count) + '</a>' : ''; }},
            {label: 'Errors', title: 'Packet errors since the counters were cleared', key: 'errors', sortValue: function (p) { return p.errors; },
                render: function (p) { return p.errors ? '<span class="text-danger">' + esc(p.errors) + '</span>' : ''; }},
            {label: 'Flaps', title: 'Link-down messages in the switch log (switch-wide outages excluded)', key: 'flaps',
                sortValue: function (p) { return p.flaps; },
                render: function (p) { return p.flaps ? '<span class="' + (p.flaps >= 5 ? 'text-warning' : 'text-muted') + '">' + esc(p.flaps) + '</span>' : ''; }}
        ];
        if (canChange) {
            cols.push({label: '', sort: false, csv: false, render: function (p) {
                return '<button type="button" class="btn btn-default btn-xs instanton-port-edit" data-port="' + esc(p.name) +
                    '" title="Description, enable/disable, PoE, power-cycle, cable test">' + icon('pencil') + '</button>';
            }});
        }
        return cols;
    }

    function accessPointsPage($root) {
        var page = new Page('accesspoints', $root);
        page.loader = function () { return api('status/aps'); };
        var table, cloudTable;
        page.render = function (data) {
            if (!table) {
                page.$content.html(section('Access points', '<div id="instanton-aps"></div>') + '<div id="instanton-cloud-devices"></div>');
                table = new Table($('#instanton-aps'), {sortKey: 0, columns: apColumns(false), emptyText:
                    'No access points found. Enable discovery through the switch or add them by address in Settings.'});
            }
            table.setRows(data.aps || []);
            var cd = data.cloud_devices || [];
            if (cd.length) {
                if (!cloudTable) {
                    $('#instanton-cloud-devices').html(section('Cloud inventory', '<div id="instanton-cloud-table"></div>'));
                    cloudTable = new Table($('#instanton-cloud-table'), {sortKey: 0, columns: [
                        {label: 'Name', key: 'name'}, {label: 'Type', key: 'type'}, {label: 'Model', key: 'model'},
                        {label: 'Status', key: 'status'}, {label: 'IP', key: 'ip'}, {label: 'Firmware', key: 'firmware'},
                        {label: 'Uptime', sortValue: function (d) { return d.uptime || 0; }, render: function (d) { return esc(duration(d.uptime)); }},
                        {label: 'Radios', sort: false, render: function (d) {
                            return $.map(d.radios || [], function (r) {
                                return esc(r.band + ' ch ' + r.channel + (r.clients !== null && r.clients !== undefined ? ', ' + r.clients + ' clients' : '') +
                                    (r.utilization !== null && r.utilization !== undefined ? ', ' + r.utilization + '% busy' : ''));
                            }).join('<br>');
                        }}
                    ]});
                }
                cloudTable.setRows(cd);
            }
        };
        page.reload();
    }

    function clientsPage($root) {
        var page = new Page('clients', $root);
        page.loader = function () { return api('status/clients'); };
        var table, filters = {state: 'online', conn: '', ap: '', vlan: '', port: ''};
        var m = /#port=(.+)$/.exec(window.location.hash);
        if (m) { filters.port = decodeURIComponent(m[1]); filters.state = ''; }
        page.render = function (data) {
            var rows = data.clients || [];
            if (!table) {
                page.$content.html(section('Clients', '<div class="form-inline instanton-filters">' +
                    '<select class="form-control input-sm" data-f="state" aria-label="State"><option value="online">online now</option>' +
                    '<option value="offline">offline (history)</option><option value="">all</option></select> ' +
                    '<select class="form-control input-sm" data-f="conn" aria-label="Connection"><option value="">wired and wireless</option>' +
                    '<option value="wireless">wireless only</option><option value="wired">wired only</option></select> ' +
                    '<select class="form-control input-sm" data-f="ap" aria-label="Access point"><option value="">any access point</option></select> ' +
                    '<select class="form-control input-sm" data-f="vlan" aria-label="VLAN"><option value="">any VLAN</option></select> ' +
                    '<span class="instanton-port-filter"></span>' +
                    '<button class="btn btn-default btn-sm pull-right" type="button" id="instanton-csv">' + icon('download') + ' CSV</button>' +
                    '</div><div id="instanton-clients"></div>'));
                table = new Table($('#instanton-clients'), {sortKey: 1, columns: clientColumns(), emptyText: 'No clients seen yet.',
                    rowClass: function (c) { return c.online ? '' : 'instanton-dim'; },
                    extraFilter: function (c) {
                        if (filters.state === 'online' && !c.online) { return false; }
                        if (filters.state === 'offline' && c.online) { return false; }
                        if (filters.conn && c.connection !== filters.conn) { return false; }
                        if (filters.ap && c.ap !== filters.ap) { return false; }
                        if (filters.vlan && String(c.vlan) !== filters.vlan) { return false; }
                        if (filters.port && c.port !== filters.port) { return false; }
                        return true;
                    }});
                page.$content.find('select[data-f]').each(function () { $(this).val(filters[$(this).data('f')]); })
                    .on('change', function () { filters[$(this).data('f')] = $(this).val(); table.render(); });
                $('#instanton-csv').on('click', function () { table.csv('instanton-clients.csv'); });
            }
            var aps = {}, vlans = {};
            $.each(rows, function (_, c) { if (c.ap) { aps[c.ap] = 1; } if (c.vlan !== null && c.vlan !== undefined) { vlans[c.vlan] = 1; } });
            fillSelect(page.$content.find('select[data-f=ap]'), 'any access point', Object.keys(aps).sort(), filters.ap);
            fillSelect(page.$content.find('select[data-f=vlan]'), 'any VLAN', Object.keys(vlans).sort(function (a, b) { return a - b; }), filters.vlan);
            var $pf = page.$content.find('.instanton-port-filter');
            if (filters.port) {
                $pf.html('<span class="label label-primary">port ' + esc(filters.port) + ' <a href="#" class="instanton-clear-port" ' +
                    'style="color:#fff" aria-label="Clear port filter">&times;</a></span>');
                $pf.find('a').on('click', function (e) { e.preventDefault(); filters.port = ''; history.replaceState(null, '', window.location.pathname); $pf.empty(); table.render(); });
            }
            table.setRows(rows);
        };
        page.reload();
    }

    function fillSelect($sel, anyLabel, values, current) {
        var html = '<option value="">' + esc(anyLabel) + '</option>' + $.map(values, function (v) {
            return '<option value="' + esc(v) + '">' + esc(v) + '</option>';
        }).join('');
        if ($sel.data('html') !== html) {
            $sel.data('html', html).html(html).val(current);
        }
    }

    function clientColumns() {
        return [
            {label: 'State', sortValue: function (c) { return c.online ? 0 : 1; }, text: function (c) { return c.online ? 'online' : 'offline'; },
                render: function (c) { return c.online ? '<span class="text-success" title="online">' + icon('circle') + '</span>'
                    : '<span class="text-muted" title="last seen ' + esc(datetime(c.last_seen)) + '">' + icon('circle-o') + '</span>'; }, csvValue: function (c) { return c.online ? 'online' : 'offline'; }},
            {label: 'Name', title: 'Firewall static mapping description, DHCP host name, or the description of the switch port when it has a single device',
                text: function (c) { return c.description || c.hostname || c.port_label || ''; }, render: function (c) {
                var name = c.description || c.hostname;
                if (name) {
                    return '<b>' + esc(name) + '</b>' + (c.description && c.hostname && c.description !== c.hostname ? '<div class="small text-muted">' + esc(c.hostname) + '</div>' : '');
                }
                if (c.port_label) {
                    return esc(c.port_label) + ' <span class="text-muted small" title="Name taken from the switch port description">(port)</span>';
                }
                return '<span class="text-muted">unknown</span>';
            }},
            {label: 'IP address', key: 'ip', sortValue: function (c) {
                return c.ip ? c.ip.split('.').map(function (x) { return ('00' + x).slice(-3); }).join('.') : '';
            }, render: function (c) { return esc(c.ip) + (c.lease === 'static' ? ' ' + badge('static', 'default', 'Static DHCP mapping on the firewall') : ''); }},
            {label: 'MAC address', key: 'mac', render: function (c) {
                return '<code>' + esc(c.mac) + '</code><div class="small text-muted">' +
                    (c.random_mac ? '<span title="Randomized address used by phones and laptops for privacy">private MAC</span>' : esc(c.vendor || '')) + '</div>';
            }, csvValue: function (c) { return c.mac; }},
            {label: 'Vendor', key: 'vendor', cls: 'hidden', csv: true},
            {label: 'Connection', title: 'Access point (wireless) or switch port (wired)',
                text: function (c) { return c.connection + ' ' + (c.ap || c.port); },
                render: function (c) {
                    var where = c.connection === 'wireless' ? icon('wifi') + ' ' + esc(c.ap || 'wireless') : icon('plug') + ' port ' + esc(c.port);
                    var extra = [];
                    if (c.connection === 'wireless' && c.port) { extra.push('port ' + esc(c.port)); }
                    if (c.ssid) { extra.push(esc(c.ssid)); }
                    if (c.band) { extra.push(esc(c.band)); }
                    if (c.roamed_from) { extra.push('roamed from ' + esc(c.roamed_from)); }
                    return where + (extra.length ? '<div class="small text-muted">' + extra.join(' &middot; ') + '</div>' : '');
                }},
            {label: 'VLAN', key: 'vlan', sortValue: function (c) { return c.vlan === null || c.vlan === undefined ? 9999 : c.vlan; }},
            {label: 'Signal', title: 'Signal strength (cloud source only)', sortValue: function (c) { return c.signal || -999; },
                render: function (c) {
                    if (c.signal === null || c.signal === undefined) { return ''; }
                    var cls = c.signal >= -60 ? 'success' : (c.signal >= -70 ? 'warning' : 'danger');
                    return badge(c.signal + ' dBm', cls);
                }, csvValue: function (c) { return c.signal; }},
            {label: 'First seen', sortValue: function (c) { return c.first_seen || 0; }, text: function (c) { return datetime(c.first_seen); },
                render: function (c) { return '<span title="' + esc(datetime(c.first_seen)) + '">' + esc(ago(c.first_seen)) + '</span>'; }},
            {label: 'Last seen', sortValue: function (c) { return c.last_seen || 0; }, text: function (c) { return datetime(c.last_seen); },
                render: function (c) { return c.online ? '<span class="text-success">now</span>' : '<span title="' + esc(datetime(c.last_seen)) + '">' + esc(ago(c.last_seen)) + '</span>'; }}
        ];
    }

    function eventsPage($root) {
        var page = new Page('events', $root);
        page.loader = function () { return api('status/events'); };
        var table, level = '', area = '';
        page.render = function (data) {
            var rows = data.events || [];
            if (!table) {
                page.$content.html(section('Events', '<div class="form-inline instanton-filters">' +
                    '<select class="form-control input-sm" id="instanton-ev-level" aria-label="Level"><option value="">all levels</option>' +
                    '<option value="warning">warnings and errors</option><option value="error">errors only</option></select> ' +
                    '<select class="form-control input-sm" id="instanton-ev-area" aria-label="Area"><option value="">all areas</option></select>' +
                    '<button class="btn btn-default btn-sm pull-right" type="button" id="instanton-ev-csv">' + icon('download') + ' CSV</button></div>' +
                    '<div id="instanton-events"></div>'));
                var rank = {error: 0, warning: 1, info: 2};
                table = new Table($('#instanton-events'), {sortKey: 0, sortDir: -1, emptyText:
                    'No events yet. Changes are recorded from the second poll on.', columns: [
                    {label: 'Time', sortValue: function (e) { return e.time; }, text: function (e) { return datetime(e.time); },
                        render: function (e) { return '<span class="text-nowrap">' + esc(datetime(e.time)) + '</span><div class="small text-muted">' + esc(ago(e.time)) + '</div>'; }},
                    {label: 'Level', key: 'level', render: function (e) { return levelBadge(e.level); }},
                    {label: 'Area', key: 'area'},
                    {label: 'Event', key: 'message'}
                ], extraFilter: function (e) {
                    if (level && rank[e.level] > rank[level]) { return false; }
                    return !area || e.area === area;
                }});
                $('#instanton-ev-level').on('change', function () { level = $(this).val(); table.render(); });
                $('#instanton-ev-area').on('change', function () { area = $(this).val(); table.render(); });
                $('#instanton-ev-csv').on('click', function () { table.csv('instanton-events.csv'); });
            }
            var areas = {};
            $.each(rows, function (_, e) { areas[e.area] = 1; });
            fillSelect($('#instanton-ev-area'), 'all areas', Object.keys(areas).sort(), area);
            table.setRows(rows);
        };
        page.reload();
    }

    function settingsHelp($target) {
        $target.prepend(helpPanel('settings'));
    }

    function showTestResult($target, data) {
        if (!data || data.status !== 'ok') {
            $target.html('<div class="alert alert-danger">' + esc((data && data.message) || 'Test failed.') + '</div>');
            return;
        }
        var names = {switch: 'Switch', aps: 'Access points', cloud: 'Cloud'};
        $target.html($.map(data.result || {}, function (r, k) {
            var kind = r.ok === true ? 'success' : (r.ok === false ? 'danger' : 'info');
            var ic = r.ok === true ? 'check-circle' : (r.ok === false ? 'times-circle' : 'info-circle');
            return '<div class="alert alert-' + kind + ' instanton-test">' + icon(ic) + ' <b>' + esc(names[k] || k) + ':</b> ' + esc(r.message) + '</div>';
        }).join(''));
    }

    // ------------------------------------------------------------------
    // configuration changes
    // ------------------------------------------------------------------
    var canChange = false;

    function applyChange(action, params) {
        return $.ajax({url: API + 'config/apply', type: 'POST', dataType: 'json', cache: false,
            data: {request: JSON.stringify({action: action, params: params || {}})}});
    }

    function notice($target, kind, html) {
        var $n = $('<div class="alert alert-' + kind + ' alert-dismissible instanton-notice">' +
            '<button type="button" class="close" data-dismiss="alert" aria-label="Close">&times;</button>' + html + '</div>');
        $target.prepend($n);
        if (kind === 'success') { setTimeout(function () { $n.fadeOut(400, function () { $n.remove(); }); }, 8000); }
        return $n;
    }

    function changeResult($target, res) {
        if (res && res.status === 'ok') {
            notice($target, 'success', icon('check-circle') + ' ' + esc(res.message) +
                (res.saved === false ? ' <b>Not saved</b>: it is lost when the switch restarts.' : ''));
            return true;
        }
        notice($target, 'danger', icon('times-circle') + ' ' + esc((res && res.message) || 'The change failed.'));
        return false;
    }

    // simple Bootstrap 3 modal; fields: [{name, label, type, value, options, help}]
    function dialog(opts) {
        var $m = $('<div class="modal fade instanton-modal" tabindex="-1" role="dialog"><div class="modal-dialog' +
            (opts.wide ? ' modal-lg' : '') + '" role="document"><div class="modal-content"><div class="modal-header">' +
            '<button type="button" class="close" data-dismiss="modal" aria-label="Close">&times;</button>' +
            '<h4 class="modal-title">' + esc(opts.title) + '</h4></div><div class="modal-body"></div>' +
            '<div class="modal-footer"><span class="instanton-modal-status text-muted pull-left"></span>' +
            '<button type="button" class="btn btn-default" data-dismiss="modal">Cancel</button>' +
            '<button type="button" class="btn btn-primary instanton-ok">' + esc(opts.ok || 'Apply') + '</button></div></div></div></div>');
        var $body = $m.find('.modal-body');
        if (opts.intro) { $body.append('<p>' + opts.intro + '</p>'); }
        $.each(opts.fields || [], function (_, f) {
            var id = 'instanton-f-' + Math.random().toString(36).slice(2);
            var input;
            if (f.type === 'checkbox') {
                input = '<div class="checkbox"><label><input type="checkbox" id="' + id + '" data-name="' + esc(f.name) + '"' +
                    (f.value ? ' checked' : '') + '> ' + esc(f.label) + '</label></div>';
            } else if (f.type === 'select') {
                input = '<label for="' + id + '">' + esc(f.label) + '</label><select class="form-control" id="' + id + '" data-name="' +
                    esc(f.name) + '">' + $.map(f.options, function (o) {
                        return '<option value="' + esc(o[0]) + '"' + (String(o[0]) === String(f.value) ? ' selected' : '') + '>' + esc(o[1]) + '</option>';
                    }).join('') + '</select>';
            } else {
                input = '<label for="' + id + '">' + esc(f.label) + '</label><input type="text" class="form-control" id="' + id +
                    '" data-name="' + esc(f.name) + '" value="' + esc(f.value) + '"' + (f.placeholder ? ' placeholder="' + esc(f.placeholder) + '"' : '') +
                    (f.readonly ? ' readonly' : '') + '>';
            }
            $body.append('<div class="form-group">' + input + (f.help ? '<p class="help-block small">' + f.help + '</p>' : '') + '</div>');
        });
        if (opts.confirm) {
            $body.append('<div class="alert alert-warning instanton-confirm"><label style="font-weight:normal"><input type="checkbox" ' +
                'class="instanton-confirm-box"> ' + opts.confirm + '</label></div>');
        }
        if (opts.extra) { $body.append(opts.extra); }
        var $ok = $m.find('.instanton-ok');
        if (opts.confirm) {
            $ok.prop('disabled', true);
            $m.find('.instanton-confirm-box').on('change', function () { $ok.prop('disabled', !this.checked); });
        }
        $ok.on('click', function () {
            var values = {};
            $body.find('[data-name]').each(function () {
                var $i = $(this);
                values[$i.data('name')] = $i.is(':checkbox') ? $i.is(':checked') : $i.val();
            });
            $ok.prop('disabled', true);
            $m.find('.instanton-modal-status').html(icon('spinner fa-pulse') + ' Talking to the switch...');
            $.when(opts.submit(values)).always(function () { $m.modal('hide'); });
        });
        $m.on('hidden.bs.modal', function () { $m.remove(); });
        $('body').append($m);
        $m.modal('show');
        return $m;
    }

    function portDialog(p, $notice, after) {
        var poe = p.poe;
        var uplink = p.role === 'uplink';
        var tools = $('<div class="instanton-port-tools"></div>');
        if (poe && poe.enabled) {
            tools.append($('<button type="button" class="btn btn-default btn-sm">' + icon('power-off') + ' Power-cycle PoE</button>')
                .on('click', function () {
                    $(this).closest('.modal').modal('hide');
                    dialog({title: 'Power-cycle PoE on port ' + p.name, ok: 'Power-cycle',
                        intro: 'Power to the device on this port is cut for a moment and restored. Use it to restart a hung ' +
                            'access point, camera or phone. The device needs its usual boot time to come back.',
                        submit: function () { return applyChange('poe_cycle', {port: p.name}).done(function (r) { changeResult($notice, r); after(); }); }});
                }));
        }
        if (!uplink) {
            tools.append(' ', $('<button type="button" class="btn btn-default btn-sm">' + icon('stethoscope') + ' Test cable</button>')
                .on('click', function () {
                    $(this).closest('.modal').modal('hide');
                    dialog({title: 'Cable test on port ' + p.name, ok: 'Start test',
                        intro: 'The switch measures the copper pairs of the cable (length, open or short circuits). ' +
                            'The results appear in the switch web interface under Diagnostics &gt; Cable Test, or on the ' +
                            '<a href="/ui/instanton/index/configuration#ports">Configuration</a> page (Cable test section).',
                        confirm: 'The link of this port drops for a few seconds during the test.',
                        submit: function () { return applyChange('cable_test', {port: p.name, confirm: true}).done(function (r) { changeResult($notice, r); }); }});
                }));
        }
        var fields = [
            {name: 'description', label: 'Description', value: p.description, help: 'Shown on the switch and in this plugin; ' +
                'a port with one device and a description names that device in the client list. Up to 64 characters.'},
            {name: 'enabled', label: 'Port enabled', type: 'checkbox', value: p.enabled, help: uplink ?
                '<b>This port leads to the firewall and cannot be switched off from here.</b>' :
                'A disabled port carries no traffic and gives no PoE power.'}
        ];
        if (poe) {
            fields.push({name: 'poe', label: 'PoE enabled', type: 'checkbox', value: poe.enabled,
                help: 'Turning PoE off powers down the connected access point, camera or phone.'});
        }
        dialog({title: 'Port ' + p.name + (p.description ? ' - ' + p.description : ''), fields: fields,
            extra: tools.children().length ? $('<div><label>Tools</label><div></div></div>').find('div').append(tools).end() : null,
            submit: function (v) {
                var steps = [];
                var params = {port: p.name};
                if (v.description !== (p.description || '')) { params.description = v.description; }
                if (!uplink && v.enabled !== p.enabled) { params.enabled = v.enabled; }
                if (Object.keys(params).length > 1) { steps.push(['port', params]); }
                if (poe && v.poe !== poe.enabled) { steps.push(['poe', {port: p.name, enabled: v.poe}]); }
                if (!steps.length) { notice($notice, 'info', 'Nothing changed.'); return null; }
                var chain = $.Deferred().resolve().promise();
                $.each(steps, function (_, s) {
                    chain = chain.then(function () {
                        return applyChange(s[0], s[1]).then(function (r) { changeResult($notice, r); });
                    });
                });
                return chain.always(after);
            }});
    }

    // ---- configuration page --------------------------------------------
    var TZ_OFFSETS = ['-12:00', '-11:00', '-10:00', '-09:30', '-09:00', '-08:00', '-07:00', '-06:00', '-05:00', '-04:00',
        '-03:30', '-03:00', '-02:00', '-01:00', '+00:00', '+01:00', '+02:00', '+03:00', '+03:30', '+04:00', '+04:30',
        '+05:00', '+05:30', '+05:45', '+06:00', '+06:30', '+07:00', '+08:00', '+09:00', '+09:30', '+10:00', '+10:30',
        '+11:00', '+12:00', '+12:45', '+13:00', '+14:00'];
    var RISK = {
        normal: ['', ''],
        caution: ['warning', 'Can interrupt traffic: changes need a confirmation'],
        blocked: ['danger', 'Controls access to the switch: read-only here, change it from the switch web interface']
    };

    function humanize(name) {
        return String(name).replace(/_/g, ' ').replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
            .replace(/^./, function (c) { return c.toUpperCase(); });
    }

    function isFlagField(name, value) {
        return (value === '1' || value === '2') && /(enable|enabled|enbl|state|status|mode)$/i.test(name);
    }

    function scalarFields(obj) {
        var out = {};
        $.each(obj || {}, function (k, v) { if (v === null || typeof v !== 'object') { out[k] = v; } });
        return out;
    }

    function tableRows(section, rowTag) {
        if (!section || typeof section !== 'object') { return {tag: rowTag, rows: []}; }
        var keys = Object.keys(section);
        var tag = rowTag && section[rowTag] !== undefined ? rowTag : (keys.length === 1 ? keys[0] : rowTag);
        var rows = section[tag];
        if (!rows) { return {tag: tag, rows: []}; }
        return {tag: tag, rows: $.isArray(rows) ? rows : [rows]};
    }

    function valueInput(name, value) {
        if (isFlagField(name, value)) {
            return {name: name, label: humanize(name), type: 'select', value: value,
                options: [['1', 'enabled (1)'], ['2', 'disabled (2)']]};
        }
        return {name: name, label: humanize(name), value: value};
    }

    function configurationPage($root) {
        var page = new Page('configuration', $root);
        var data = null;
        var group = (window.location.hash || '#system').slice(1);
        page.noMeta = true;
        page.$bar.find('.instanton-auto, .instanton-refresh').remove();
        page.loader = function () { return $.ajax({url: API + 'config/read/cached', dataType: 'json', cache: false}); };

        function read(what) {
            var $btn = page.$content.find('.instanton-read');
            $btn.prop('disabled', true).find('i').addClass('fa-spin');
            return $.ajax({url: API + 'config/read/' + encodeURIComponent(what), type: 'POST', dataType: 'json', cache: false})
                .done(function (d) {
                    if (d.status !== 'ok') { notice(page.$banner, 'danger', esc(d.message || 'Cannot read the switch.')); return; }
                    data = d;
                    draw();
                }).always(function () { $btn.prop('disabled', false).find('i').removeClass('fa-spin'); });
        }

        function after(section) {
            return function () { return read(section || group); };
        }

        function commonTasks() {
            var sw = data.sections || {};
            var sys = sw.SystemGlobalSetting || {};
            var ts = sw.TimeSetting || {};
            var tz = ts.TimeZone || {};
            var servers = tableRows(sw.SNTPServerTable, 'SNTPServerEntry').rows;
            var sys_srv = tableRows(sw.SyslogServerList, 'SyslogServer').rows;
            var dst = ts.dayLightSavingMode === '3' || !ts.dayLightSavingMode ? 'off' : 'custom';
            var rec = (ts.DayLightSaving || {}).RecurrentPeriod || {};
            if (dst === 'custom' && rec.endMonth === '10' && rec.beginWeek === '06') { dst = 'eu'; }
            if (dst === 'custom' && rec.endMonth === '11' && rec.beginWeek === '02') { dst = 'us'; }
            var off = String(tz.offsetHour || '00');
            off = (off.charAt(0) === '-' ? '-' : '+') + ('0' + off.replace(/^[+-]/, '')).slice(-2) + ':' + ('0' + (tz.offsetMinute || '0')).slice(-2);
            var html = '<div class="row">' +
                '<div class="col-md-6">' + section('System', kv([
                    ['Name', esc(sys.systemName)], ['Location', esc(sys.systemLocation)], ['Contact', esc(sys.systemContact)]
                ]) + '<button class="btn btn-default btn-sm" data-task="system">' + icon('pencil') + ' Edit</button>') + '</div>' +
                '<div class="col-md-6">' + section('Time', kv([
                    ['Source', ts.setTimeMode === '2' ? 'SNTP' : 'manual clock'],
                    ['SNTP server', esc($.map(servers, function (s) { return s.IPAddress; }).join(', ')) || '<span class="text-muted">none</span>'],
                    ['Time zone', esc((tz.timeZoneID || '') + ' (UTC' + off + ')')],
                    ['Daylight saving', esc({off: 'off', eu: 'European rule', us: 'US rule', custom: 'custom rule'}[dst])]
                ]) + '<button class="btn btn-default btn-sm" data-task="time">' + icon('pencil') + ' Edit</button>') + '</div></div>' +
                '<div class="row"><div class="col-md-6">' + section('Remote syslog', kv([
                    ['Server', sys_srv.length ? esc(sys_srv[0].IPAddr + ':' + sys_srv[0].portNo) : '<span class="text-muted">none</span>'],
                    ['Level', sys_srv.length ? esc(sys_srv[0].severity) : '']
                ]) + '<button class="btn btn-default btn-sm" data-task="syslog">' + icon('pencil') + ' Edit</button>') + '</div>' +
                '<div class="col-md-6">' + section('Switch', '<p class="small text-muted">Save the running configuration, make the ' +
                    'switch easy to find in the rack, or restart it.</p>' +
                    '<button class="btn btn-default btn-sm" data-task="save">' + icon('floppy-o') + ' Save configuration</button> ' +
                    '<button class="btn btn-default btn-sm" data-task="locate-on">' + icon('lightbulb-o') + ' Blink locator LED</button> ' +
                    '<button class="btn btn-default btn-sm" data-task="locate-off">Stop LED</button> ' +
                    '<button class="btn btn-danger btn-sm" data-task="reboot">' + icon('power-off') + ' Restart switch</button>') + '</div></div>';
            var $html = $(html);
            $html.find('[data-task]').on('click', function () {
                var task = $(this).data('task');
                var $n = page.$banner;
                var done = function (r) { changeResult($n, r); };
                if (task === 'system') {
                    dialog({title: 'System', fields: [
                        {name: 'name', label: 'Name', value: sys.systemName, help: 'Letters, digits and hyphens, up to 58 characters.'},
                        {name: 'location', label: 'Location', value: sys.systemLocation},
                        {name: 'contact', label: 'Contact', value: sys.systemContact}],
                        submit: function (v) { return applyChange('system', v).done(done).always(after('system')); }});
                } else if (task === 'time') {
                    dialog({title: 'Time', fields: [
                        {name: 'sntp_server', label: 'SNTP server', value: servers.length ? servers[0].IPAddress : '',
                            placeholder: 'e.g. the firewall address on the switch network',
                            help: 'Leave empty to use the manual clock. The firewall must answer NTP on the switch network ' +
                                '(Services &gt; Network Time, and a rule allowing UDP 123).'},
                        {name: 'timezone', label: 'Time zone offset', type: 'select', value: off,
                            options: $.map(TZ_OFFSETS, function (o) { return [[o, 'UTC' + o]]; })},
                        {name: 'timezone_name', label: 'Time zone abbreviation', value: tz.timeZoneID || 'UTC',
                            help: '1 to 4 letters, for example CET. Shown in the switch log.'},
                        {name: 'dst', label: 'Daylight saving', type: 'select', value: dst === 'custom' ? 'off' : dst,
                            options: [['off', 'off'], ['eu', 'European rule (last Sunday of March to last Sunday of October)'],
                                ['us', 'US rule (second Sunday of March to first Sunday of November)']]}],
                        submit: function (v) { return applyChange('time', v).done(done).always(after('system')); }});
                } else if (task === 'syslog') {
                    dialog({title: 'Remote syslog', fields: [
                        {name: 'enabled', label: 'Send the switch log to a syslog server', type: 'checkbox', value: !!sys_srv.length},
                        {name: 'server', label: 'Server', value: sys_srv.length ? sys_srv[0].IPAddr : '',
                            help: 'IPv4 address. To collect the log on this firewall, enable remote reception in ' +
                                'System &gt; Settings &gt; Logging and allow UDP 514 from the switch.'},
                        {name: 'port', label: 'UDP port', value: sys_srv.length ? sys_srv[0].portNo : '514'},
                        {name: 'severity', label: 'Lowest level sent', type: 'select', value: sys_srv.length ? sys_srv[0].severity : '6',
                            options: [['0', 'emergency'], ['1', 'alert'], ['2', 'critical'], ['3', 'error'], ['4', 'warning'],
                                ['5', 'notice'], ['6', 'informational'], ['7', 'debug']]}],
                        submit: function (v) { return applyChange('syslog', v).done(done).always(after('monitor')); }});
                } else if (task === 'save') {
                    applyChange('save', {}).done(done);
                } else if (task === 'locate-on' || task === 'locate-off') {
                    applyChange('locate', {on: task === 'locate-on'}).done(done);
                } else if (task === 'reboot') {
                    dialog({title: 'Restart the switch', ok: 'Restart',
                        intro: 'The running configuration is saved first (if "Save after each change" is on). Every port goes ' +
                            'down: access points, cameras and the connection to the firewall are lost for about two to five minutes.',
                        confirm: 'I understand that the whole network behind this switch stops while it restarts.',
                        submit: function () { return applyChange('reboot', {confirm: true}).done(done); }});
                }
            });
            return $html;
        }

        function sectionBox(name, meta) {
            var value = (data.sections || {})[name];
            var err = (data.errors || {})[name];
            var risk = RISK[meta.risk] || RISK.normal;
            var head = (meta.risk !== 'normal' ? ' ' + badge(meta.risk === 'blocked' ? 'read-only' : 'caution', risk[0], risk[1]) : '') +
                ((data.read_at || {})[name] ? ' <span class="small text-muted" title="' + esc(datetime(data.read_at[name])) + '">read ' +
                    esc(ago(data.read_at[name])) + '</span>' : '');
            var $box = $(section(meta.title, '', head + ' <code class="small text-muted" style="margin-left:auto">' + esc(name) + '</code>'));
            var $body = $box.find('.instanton-section-body');
            var editable = canChange && meta.risk !== 'blocked';
            var confirmText = meta.risk === 'caution' ? 'I checked this change: it can interrupt traffic on the switch.' : null;
            if (err) { $body.html('<p class="text-muted small">' + esc(err) + '</p>'); return $box; }
            if (value === undefined) { $body.html('<p class="text-muted small">Not read yet: press <b>Read from switch</b>.</p>'); return $box; }
            if (meta.kind === 'setting') {
                var fields = scalarFields(value);
                var rows = $.map(fields, function (v, k) { return [[humanize(k), esc(v)]]; });
                $body.html(Object.keys(fields).length ? kv(rows) : '<p class="text-muted small">No values.</p>');
                if (editable && Object.keys(fields).length) {
                    $body.append($('<button class="btn btn-default btn-xs">' + icon('pencil') + ' Edit</button>').on('click', function () {
                        dialog({title: meta.title, wide: true, confirm: confirmText,
                            intro: 'Change the values and press Apply; only changed fields are sent. Read-only values ' +
                                '(counters, status) are rejected by the switch.',
                            fields: $.map(fields, function (v, k) { return [valueInput(k, v)]; }),
                            submit: function (vals) {
                                var changed = {};
                                $.each(vals, function (k, v) { if (String(v) !== String(fields[k])) { changed[k] = v; } });
                                if (!Object.keys(changed).length) { notice(page.$banner, 'info', 'Nothing changed.'); return null; }
                                return applyChange('section', {section: name, op: 'set', values: changed, confirm: true})
                                    .done(function (r) { changeResult(page.$banner, r); }).always(after(name));
                            }});
                    }));
                }
                return $box;
            }
            var tr = tableRows(value, meta.row);
            if (!tr.rows.length) {
                $body.html('<p class="text-muted small">Empty.</p>');
            } else {
                var cols = [];
                $.each(tr.rows, function (_, r) { $.each(scalarFields(r), function (k) { if (cols.indexOf(k) < 0) { cols.push(k); } }); });
                var t = new Table($('<div>').appendTo($body), {search: tr.rows.length > 10, columns: $.map(cols, function (c) {
                    return [{label: humanize(c), key: c, render: function (r) {
                        var v = r[c];
                        if (c === 'interfaceName' && data.uplinks && data.uplinks.indexOf(v) >= 0) {
                            return esc(v) + ' ' + badge('firewall', 'default', 'Leads to the firewall: protected from changes');
                        }
                        return esc(v);
                    }}];
                }).concat(editable ? [{label: '', sort: false, csv: false, render: function () {
                    return '<button class="btn btn-default btn-xs instanton-row-edit" title="Edit">' + icon('pencil') + '</button> ' +
                        '<button class="btn btn-default btn-xs instanton-row-del" title="Delete">' + icon('trash') + '</button>';
                }}] : [])});
                t.setRows(tr.rows);
                $body.on('click', '.instanton-row-edit, .instanton-row-del', function () {
                    var idx = $(this).closest('tr').index();
                    var row = t.visibleRows()[idx];
                    var fields = scalarFields(row);
                    var keyFields = {};
                    $.each(['interfaceName', 'interfaceType', 'VLANID', 'unitID', 'IPAddress', 'IPAddr', 'MACAddress', 'ifIndex',
                        'sessionId', 'index', 'name', 'userName', 'groupName', 'communityName', 'viewName'], function (_, k) {
                        if (fields[k] !== undefined) { keyFields[k] = fields[k]; }
                    });
                    if ($(this).hasClass('instanton-row-del')) {
                        dialog({title: 'Delete row from ' + meta.title, ok: 'Delete',
                            intro: 'Row: <code>' + esc($.map(keyFields, function (v, k) { return k + '=' + v; }).join(' ')) + '</code>',
                            confirm: 'Delete this row from the switch configuration.',
                            submit: function () {
                                return applyChange('section', {section: name, op: 'delete', row: tr.tag, entries: [keyFields], confirm: true})
                                    .done(function (r) { changeResult(page.$banner, r); }).always(after(name));
                            }});
                        return;
                    }
                    dialog({title: meta.title, wide: true, confirm: confirmText,
                        intro: 'Only changed fields are sent, together with the fields that identify the row.',
                        fields: $.map(fields, function (v, k) {
                            var f = valueInput(k, v);
                            if (keyFields[k] !== undefined) { f.readonly = true; f.type = 'text'; }
                            return [f];
                        }),
                        submit: function (vals) {
                            var entry = $.extend({}, keyFields);
                            var n = 0;
                            $.each(vals, function (k, v) { if (keyFields[k] === undefined && String(v) !== String(fields[k])) { entry[k] = v; n++; } });
                            if (!n) { notice(page.$banner, 'info', 'Nothing changed.'); return null; }
                            return applyChange('section', {section: name, op: 'set', row: tr.tag, entries: [entry], confirm: true})
                                .done(function (r) { changeResult(page.$banner, r); }).always(after(name));
                        }});
                });
            }
            if (editable) {
                var template = tr.rows.length ? scalarFields(tr.rows[0]) : {};
                $body.append($('<button class="btn btn-default btn-xs">' + icon('plus') + ' Add row</button>').on('click', function () {
                    var fields = $.map(template, function (v, k) { return [{name: k, label: humanize(k), value: ''}]; });
                    if (!fields.length) {
                        fields = [{name: 'fields', label: 'Fields', value: '', placeholder: 'name=value; name=value',
                            help: 'The table is empty, so its field names are unknown here. Enter them as name=value pairs.'}];
                    }
                    dialog({title: 'Add row to ' + meta.title, wide: true, confirm: confirmText,
                        intro: 'Leave empty the fields the switch fills in itself (counters, status).',
                        fields: fields,
                        submit: function (vals) {
                            var entry = {};
                            if (vals.fields !== undefined && fields.length === 1 && fields[0].name === 'fields') {
                                $.each(String(vals.fields).split(';'), function (_, pair) {
                                    var m = /^\s*([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/.exec(pair);
                                    if (m) { entry[m[1]] = m[2]; }
                                });
                            } else {
                                $.each(vals, function (k, v) { if (v !== '') { entry[k] = v; } });
                            }
                            return applyChange('section', {section: name, op: 'add', row: tr.tag, entries: [entry], confirm: true})
                                .done(function (r) { changeResult(page.$banner, r); }).always(after(name));
                        }});
                }));
            }
            return $box;
        }

        function draw() {
            if (!data) { return; }
            var tabs = '<ul class="nav nav-tabs instanton-tabs" role="tablist">' + $.map(data.groups || [], function (g) {
                return '<li' + (g[0] === group ? ' class="active"' : '') + '><a href="#' + esc(g[0]) + '" data-group="' + esc(g[0]) + '">' +
                    esc(g[1]) + '</a></li>';
            }).join('') + '</ul>';
            var tools = '<div class="instanton-config-tools"><button class="btn btn-default btn-sm instanton-read" type="button" ' +
                'title="Read the sections of this tab from the switch">' + icon('download') + ' Read from switch</button> ' +
                '<button class="btn btn-default btn-sm instanton-read-all" type="button" title="Read every section (about 30 seconds)">' +
                'Read everything</button>' +
                (canChange ? '' : ' <span class="text-muted small">' + icon('lock') + ' Changes are off: tick <b>Allow changes</b> in ' +
                    '<a href="/ui/instanton/index/settings">Settings</a> to edit.</span>') + '</div>';
            page.$content.html(tabs + tools + '<div class="instanton-config-body"></div>');
            var $cb = page.$content.find('.instanton-config-body');
            if (group === 'system') { $cb.append(commonTasks()); }
            $.each(data.catalog || {}, function (name, meta) {
                if (meta.group === group) { $cb.append(sectionBox(name, meta)); }
            });
            page.$content.find('[data-group]').on('click', function (e) {
                e.preventDefault();
                group = $(this).data('group');
                history.replaceState(null, '', '#' + group);
                var missing = $.grep(Object.keys(data.catalog), function (n) {
                    return data.catalog[n].group === group && data.sections[n] === undefined && !(data.errors || {})[n];
                });
                draw();
                if (missing.length) { read(group); }
            });
            page.$content.find('.instanton-read').on('click', function () { read(group); });
            page.$content.find('.instanton-read-all').on('click', function () { read('all'); });
        }

        page.render = function (d) {
            if (d.status !== 'ok') { page.$content.html('<p class="text-danger">' + esc(d.message || 'No data.') + '</p>'); return; }
            data = d;
            canChange = !!d.allow_changes;
            var empty = !Object.keys(d.sections || {}).length;
            draw();
            if (empty) { read(group); }
        };
        page.reload();
    }

    window.InstantOn = {
        esc: esc, api: api, duration: duration, ago: ago, datetime: datetime, bytes: bytes, bps: bps,
        frontPanel: frontPanel, helpPanel: helpPanel, settingsHelp: settingsHelp, showTestResult: showTestResult,
        pages: {overview: overview, 'switch': switchPage, accesspoints: accessPointsPage, clients: clientsPage, events: eventsPage,
                configuration: configurationPage}
    };
}(window, jQuery));
