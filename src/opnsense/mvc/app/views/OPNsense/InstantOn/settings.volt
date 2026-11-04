{{ partial("OPNsense/InstantOn/common") }}
<script>
    $( document ).ready(function () {
        InstantOn.settingsHelp($('#instanton-settings-help'));
        var data_get_map = {'frm_settings': '/api/instanton/settings/get'};
        mapDataToFormUI(data_get_map).done(function () {
            formatTokenizersUI();
            $('.selectpicker').selectpicker('refresh');
            updateServiceControlUI('instanton');
        });

        $("#grid-switches").UIBootgrid({
            search: '/api/instanton/settings/searchSwitch',
            get: '/api/instanton/settings/getSwitch/',
            set: '/api/instanton/settings/setSwitch/',
            add: '/api/instanton/settings/addSwitch/',
            del: '/api/instanton/settings/delSwitch/',
            toggle: '/api/instanton/settings/toggleSwitch/'
        });

        var $accounts = $("#grid-accounts").UIBootgrid({
            search: '/api/instanton/settings/searchAccount',
            get: '/api/instanton/settings/getAccount/',
            set: '/api/instanton/settings/setAccount/',
            add: '/api/instanton/settings/addAccount/',
            del: '/api/instanton/settings/delAccount/',
            toggle: '/api/instanton/settings/toggleAccount/',
            commands: {
                sites: {
                    method: function () {
                        InstantOn.cloudSites($(this).data('row-id'), function () {
                            $accounts.bootgrid('reload');
                        });
                    },
                    classname: 'fa fa-fw fa-map-marker',
                    title: "{{ lang._('Choose the sites to read') }}",
                    sequence: 5
                }
            }
        });

        $("#reconfigureAct").SimpleActionButton({
            onPreAction: function () {
                const dfObj = new $.Deferred();
                saveFormToEndpoint('/api/instanton/settings/set', 'frm_settings', function () {
                    dfObj.resolve();
                }, true, function () {
                    dfObj.reject();
                });
                return dfObj;
            },
            onAction: function () {
                updateServiceControlUI('instanton');
            }
        });

        $("#testAct").click(function () {
            var $btn = $(this);
            $btn.prop('disabled', true).find('i').removeClass('fa-plug').addClass('fa-spinner fa-pulse');
            $('#instanton-test-result').html('<div class="text-muted">{{ lang._('Saving settings and contacting the devices...') }}</div>');
            saveFormToEndpoint('/api/instanton/settings/set', 'frm_settings', function () {
                InstantOn.api('service/test', 'POST').done(function (data) {
                    InstantOn.showTestResult($('#instanton-test-result'), data);
                }).fail(function (xhr) {
                    InstantOn.showTestResult($('#instanton-test-result'), {status: 'error', message: 'HTTP ' + xhr.status});
                }).always(function () {
                    $btn.prop('disabled', false).find('i').removeClass('fa-spinner fa-pulse').addClass('fa-plug');
                });
            }, true, function () {
                $btn.prop('disabled', false).find('i').removeClass('fa-spinner fa-pulse').addClass('fa-plug');
                $('#instanton-test-result').empty();
            });
        });
    });
</script>

<div id="instanton-settings-help"></div>
<div class="content-box">
    {{ partial("layout_partials/base_form", ['fields': settingsForm, 'id': 'frm_settings']) }}
</div>

<div class="content-box instanton-grid-box">
    <h3>{{ lang._('Switches (local management)') }}</h3>
    <p class="text-muted small">
        {{ lang._('Every Instant On 1930/1960 switch in local management mode that the monitor should read. Links between the switches are found automatically. Each switch has its own account, uplink ports and save option.') }}
    </p>
    <table id="grid-switches" class="table table-condensed table-hover table-striped" data-editDialog="DialogSwitch" data-editAlert="instantonChangeMessage">
        <thead>
        <tr>
            <th data-column-id="uuid" data-type="string" data-identifier="true" data-visible="false">{{ lang._('ID') }}</th>
            <th data-column-id="enabled" data-width="6em" data-type="string" data-formatter="rowtoggle">{{ lang._('Enabled') }}</th>
            <th data-column-id="name" data-type="string">{{ lang._('Name') }}</th>
            <th data-column-id="host" data-type="string">{{ lang._('Address') }}</th>
            <th data-column-id="username" data-type="string">{{ lang._('User') }}</th>
            <th data-column-id="uplink_ports" data-type="string">{{ lang._('Uplink ports') }}</th>
            <th data-column-id="commands" data-width="7em" data-formatter="commands" data-sortable="false">{{ lang._('Commands') }}</th>
        </tr>
        </thead>
        <tbody></tbody>
        <tfoot>
        <tr>
            <td></td>
            <td>
                <button data-action="add" type="button" class="btn btn-xs btn-primary"><span class="fa fa-fw fa-plus"></span></button>
                <button data-action="deleteSelected" type="button" class="btn btn-xs btn-default"><span class="fa fa-fw fa-trash-o"></span></button>
            </td>
        </tr>
        </tfoot>
    </table>
</div>

<div class="content-box instanton-grid-box">
    <h3>{{ lang._('Instant On cloud accounts (optional)') }}</h3>
    <p class="text-muted small">
        {{ lang._('Add the data only the Instant On cloud knows: Wi-Fi networks, signal and band of every wireless client, mesh links between access points, radio channels and alerts. Each account can read one, several or all of its sites; the map pin button lists the sites of a saved account. The cloud API is undocumented and can change; accounts with two-factor authentication are not supported.') }}
    </p>
    <table id="grid-accounts" class="table table-condensed table-hover table-striped" data-editDialog="DialogAccount" data-editAlert="instantonChangeMessage">
        <thead>
        <tr>
            <th data-column-id="uuid" data-type="string" data-identifier="true" data-visible="false">{{ lang._('ID') }}</th>
            <th data-column-id="enabled" data-width="6em" data-type="string" data-formatter="rowtoggle">{{ lang._('Enabled') }}</th>
            <th data-column-id="name" data-type="string">{{ lang._('Name') }}</th>
            <th data-column-id="username" data-type="string">{{ lang._('Account') }}</th>
            <th data-column-id="sites" data-type="string">{{ lang._('Sites (empty = all)') }}</th>
            <th data-column-id="commands" data-width="9em" data-formatter="commands" data-sortable="false">{{ lang._('Commands') }}</th>
        </tr>
        </thead>
        <tbody></tbody>
        <tfoot>
        <tr>
            <td></td>
            <td>
                <button data-action="add" type="button" class="btn btn-xs btn-primary"><span class="fa fa-fw fa-plus"></span></button>
                <button data-action="deleteSelected" type="button" class="btn btn-xs btn-default"><span class="fa fa-fw fa-trash-o"></span></button>
            </td>
        </tr>
        </tfoot>
    </table>
</div>

<div class="alert alert-info hidden" role="alert" id="instantonChangeMessage">
    {{ lang._('After changing switches or accounts press Apply to restart the monitor with the new list.') }}
</div>

<div class="content-box" style="padding: 10px 15px;">
    <div id="instanton-test-result"></div>
    <button class="btn btn-primary" id="reconfigureAct"
            data-endpoint="/api/instanton/service/reconfigure"
            data-label="{{ lang._('Apply') }}"
            data-error-title="{{ lang._('Error applying the Instant On settings') }}"
            type="button"></button>
    <button class="btn btn-default" id="testAct" type="button"
            title="{{ lang._('Save the settings and check that every switch, access point and cloud account answers') }}">
        <i class="fa fa-plug"></i> {{ lang._('Test connection') }}
    </button>
    <span class="text-muted small" style="margin-left: 10px;">
        {{ lang._('Apply saves the settings and restarts the monitor. Test connection saves them and checks the devices without starting it.') }}
    </span>
</div>

{{ partial("layout_partials/base_dialog", ['fields': switchForm, 'id': 'DialogSwitch', 'label': lang._('Switch')]) }}
{{ partial("layout_partials/base_dialog", ['fields': accountForm, 'id': 'DialogAccount', 'label': lang._('Cloud account')]) }}
