/*
 * Instant On monitor - dashboard widget.
 * Copyright (C) 2026 os-instanton contributors. BSD 2-Clause license.
 */
import BaseTableWidget from "./BaseTableWidget.js";

export default class InstantOn extends BaseTableWidget {
    constructor() {
        super();
        this.tickTimeout = 30;
    }

    getGridOptions() {
        return {
            sizeToContent: 650
        };
    }

    getMarkup() {
        let $container = $('<div></div>');
        let $table = this.createTable('instanton-table', {
            headerPosition: 'left'
        });
        $container.append($table);
        return $container;
    }

    _esc(value) {
        return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[c]);
    }

    async onWidgetTick() {
        const data = await this.ajaxCall('/api/instanton/status/summary');
        const t = this.translations;
        if (!data || !data.meta || !data.meta.generated) {
            this.updateTable('instanton-table', [[t.status, `<a href="/ui/instanton/index/settings">${t.nodata}</a>`]]);
            return;
        }
        const s = data.summary || {};
        const switches = data.switches || [];
        const temps = switches.map((x) => x.temperature).filter((x) => x !== null && x !== undefined);
        const ok = (v) => `<i class="fa fa-circle text-${v ? 'success' : 'danger'}"></i>`;
        const swText = switches.length > 1
            ? `${s.switches_online} / ${s.switches_total} ${t.online} &middot; ${s.ports_up} / ${s.ports_total} ${t.ports}`
            : (s.switch_online ? `${s.ports_up} / ${s.ports_total} ${t.ports}` : t.offline);
        const rows = [
            [t.switch, `${ok(s.switch_online)} <a href="/ui/instanton/index/switch">${swText}</a>` +
                (temps.length ? ` &middot; ${this._esc(Math.max(...temps))} &deg;C` : '')],
            [t.aps, `${ok(s.aps_total && s.aps_online === s.aps_total)} <a href="/ui/instanton/index/accesspoints">` +
                `${s.aps_online} / ${s.aps_total} ${t.online}</a>`],
            [t.clients, `<a href="/ui/instanton/index/clients">${s.clients_online}</a> ` +
                `(${s.clients_wireless} ${t.wireless}, ${s.clients_wired} ${t.wired})`]
        ];
        if (s.poe_w !== null && s.poe_w !== undefined) {
            rows.push([t.poe, `${this._esc(s.poe_w)} W (${this._esc(s.poe_percent)}%)`]);
        }
        const problems = (data.insights || []).filter((i) => i.level !== 'info');
        rows.push([t.checks, problems.length
            ? problems.slice(0, 3).map((i) => `<div class="text-${i.level === 'critical' ? 'danger' : 'warning'}">` +
                `<i class="fa fa-exclamation-triangle"></i> ${this._esc(i.title)}</div>`).join('') +
                (problems.length > 3 ? `<a href="/ui/instanton/">+${problems.length - 3} ${t.more}</a>` : '')
            : `<span class="text-success"><i class="fa fa-check"></i> ${t.allgood}</span>`]);
        this.updateTable('instanton-table', rows);
    }
}
