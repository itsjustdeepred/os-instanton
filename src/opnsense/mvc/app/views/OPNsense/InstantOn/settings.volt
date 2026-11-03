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
<div class="content-box" style="padding: 10px 15px;">
    <div id="instanton-test-result"></div>
    <button class="btn btn-primary" id="reconfigureAct"
            data-endpoint="/api/instanton/service/reconfigure"
            data-label="{{ lang._('Apply') }}"
            data-error-title="{{ lang._('Error applying the Instant On settings') }}"
            type="button"></button>
    <button class="btn btn-default" id="testAct" type="button"
            title="{{ lang._('Save the settings and check that every source answers') }}">
        <i class="fa fa-plug"></i> {{ lang._('Test connection') }}
    </button>
    <span class="text-muted small" style="margin-left: 10px;">
        {{ lang._('Apply saves the settings and restarts the monitor. Test connection saves them and checks the devices without starting it.') }}
    </span>
</div>
