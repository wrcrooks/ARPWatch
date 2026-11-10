{#
 # ARPWatch plugin settings page
 # SPDX-License-Identifier: BSD-2-Clause
 #}

<script>
    $(document).ready(function () {
        const forms = ['frm_general', 'frm_notifications'];
        const methodNames = {smtp: 'SMTP', telegram: 'Telegram', pushbullet: 'Pushbullet'};

        mapDataToFormUI({
            'frm_general': '/api/arpwatch/settings/get',
            'frm_notifications': '/api/arpwatch/settings/get'
        }).done(function () {
            formatTokenizersUI();
            $('.selectpicker').selectpicker('refresh');
            updateServiceControlUI('arpwatch');
        });

        /* both tabs belong to one model, save them in a single request so validation sees everything */
        function saveSettings() {
            const dfd = $.Deferred();
            const data = $.extend(true, {}, getFormData('frm_general'), getFormData('frm_notifications'));
            ajaxCall('/api/arpwatch/settings/set', data, function (response, status) {
                const validations = (response && response.validations) || {};
                forms.forEach(function (form) {
                    handleFormValidation(form, validations);
                });
                if (status === 'success' && response.result === 'saved') {
                    dfd.resolve();
                    return;
                }
                /* jump to the first tab holding an invalid field */
                const first = Object.keys(validations)[0] || '';
                if (first.indexOf('arpwatch.notifications.') === 0) {
                    $('#tab_notifications_link').tab('show');
                } else if (first !== '') {
                    $('#tab_general_link').tab('show');
                }
                BootstrapDialog.show({
                    type: BootstrapDialog.TYPE_WARNING,
                    title: "{{ lang._('ARPWatch') }}",
                    message: "{{ lang._('The settings could not be saved, please correct the highlighted fields.') }}",
                    buttons: [{label: "{{ lang._('Close') }}", action: function (dlg) { dlg.close(); }}]
                });
                dfd.reject();
            });
            return dfd.promise();
        }

        $('#saveAct').click(function () {
            $('#saveAct_progress').addClass('fa fa-spinner fa-pulse');
            saveSettings().done(function () {
                ajaxCall('/api/arpwatch/service/reconfigure', {}, function () {
                    updateServiceControlUI('arpwatch');
                    $('#saveAct_progress').removeClass('fa fa-spinner fa-pulse');
                });
            }).fail(function () {
                $('#saveAct_progress').removeClass('fa fa-spinner fa-pulse');
            });
        });

        $('#testAct').click(function () {
            $('#testAct_progress').addClass('fa fa-spinner fa-pulse');
            saveSettings().done(function () {
                ajaxCall('/api/arpwatch/service/test', {}, function (response) {
                    $('#testAct_progress').removeClass('fa fa-spinner fa-pulse');
                    const results = (response && response.results) || {};
                    const $list = $('<ul class="list-unstyled"></ul>');
                    Object.keys(results).forEach(function (name) {
                        const ok = results[name].success;
                        $list.append($('<li></li>').append(
                            $('<i class="fa fa-fw"></i>').addClass(ok ? 'fa-check text-success' : 'fa-times text-danger'),
                            $('<b></b>').text(' ' + (methodNames[name] || name) + ': '),
                            $('<span></span>').text(results[name].message)
                        ));
                    });
                    if ($list.children().length === 0) {
                        $list.append($('<li></li>').text(
                            "{{ lang._('Nothing was sent. Enable at least one notification method first.') }}"
                        ));
                    }
                    BootstrapDialog.show({
                        type: response && response.status === 'ok' ? BootstrapDialog.TYPE_SUCCESS : BootstrapDialog.TYPE_WARNING,
                        title: "{{ lang._('Test notification') }}",
                        message: $list,
                        buttons: [{label: "{{ lang._('Close') }}", action: function (dlg) { dlg.close(); }}]
                    });
                });
            }).fail(function () {
                $('#testAct_progress').removeClass('fa fa-spinner fa-pulse');
            });
        });

        const $grid = $('#grid-hosts').UIBootgrid({
            search: '/api/arpwatch/hosts/search',
            del: '/api/arpwatch/hosts/del/',
            options: {
                selection: false,
                multiSelect: false,
                formatters: {
                    commands: function (column, row) {
                        return '<button type="button" class="btn btn-xs btn-default command-delete bootgrid-tooltip" ' +
                            'title="{{ lang._('Forget this device') }}" data-row-id="' + row.id + '">' +
                            '<span class="fa fa-fw fa-trash-o"></span></button>';
                    }
                }
            }
        });

        $('#tab_hosts_link').on('shown.bs.tab', function () {
            $grid.bootgrid('reload');
        });

        $('#flushAct').click(function () {
            BootstrapDialog.confirm({
                type: BootstrapDialog.TYPE_DANGER,
                title: "{{ lang._('Forget all devices') }}",
                message: "{{ lang._('Remove every device from the database? Each of them is treated as new the next time it is seen.') }}",
                btnOKLabel: "{{ lang._('Yes') }}",
                btnCancelLabel: "{{ lang._('Cancel') }}",
                callback: function (confirmed) {
                    if (confirmed) {
                        ajaxCall('/api/arpwatch/hosts/flush', {}, function () {
                            $grid.bootgrid('reload');
                        });
                    }
                }
            });
        });

        /* settings buttons make no sense on the device list */
        $('a[data-toggle="tab"]').on('shown.bs.tab', function (e) {
            $('#settings_buttons').toggle($(e.target).attr('id') !== 'tab_hosts_link');
        });
    });
</script>

<ul class="nav nav-tabs" data-tabs="tabs" id="maintabs">
    <li class="active"><a data-toggle="tab" href="#tab_general" id="tab_general_link">{{ lang._('General') }}</a></li>
    <li><a data-toggle="tab" href="#tab_notifications" id="tab_notifications_link">{{ lang._('Notifications') }}</a></li>
    <li><a data-toggle="tab" href="#tab_hosts" id="tab_hosts_link">{{ lang._('Devices') }}</a></li>
</ul>

<div class="tab-content content-box">
    <div id="tab_general" class="tab-pane fade in active">
        {{ partial("layout_partials/base_form", ['fields': generalForm, 'id': 'frm_general']) }}
    </div>
    <div id="tab_notifications" class="tab-pane fade in">
        {{ partial("layout_partials/base_form", ['fields': notificationsForm, 'id': 'frm_notifications']) }}
    </div>
    <div id="tab_hosts" class="tab-pane fade in">
        <table id="grid-hosts" class="table table-condensed table-hover table-striped table-responsive">
            <thead>
                <tr>
                    <th data-column-id="id" data-type="string" data-identifier="true" data-visible="false">{{ lang._('ID') }}</th>
                    <th data-column-id="mac" data-type="string">{{ lang._('MAC address') }}</th>
                    <th data-column-id="vendor" data-type="string">{{ lang._('Vendor') }}</th>
                    <th data-column-id="hostname" data-type="string">{{ lang._('Hostname') }}</th>
                    <th data-column-id="addresses" data-type="string">{{ lang._('IP addresses') }}</th>
                    <th data-column-id="interface" data-type="string">{{ lang._('Interface') }}</th>
                    <th data-column-id="first_seen" data-type="string" data-order="desc">{{ lang._('First seen') }}</th>
                    <th data-column-id="last_seen" data-type="string">{{ lang._('Last seen') }}</th>
                    <th data-column-id="commands" data-width="5em" data-formatter="commands" data-sortable="false">{{ lang._('Forget') }}</th>
                </tr>
            </thead>
            <tbody>
            </tbody>
            <tfoot>
                <tr>
                    <td colspan="8"></td>
                    <td>
                        <button id="flushAct" type="button" class="btn btn-xs btn-danger" title="{{ lang._('Forget all devices') }}">
                            <span class="fa fa-fw fa-trash-o"></span>
                        </button>
                    </td>
                </tr>
            </tfoot>
        </table>
    </div>
</div>

<section class="page-content-main" id="settings_buttons">
    <div class="content-box">
        <div class="col-md-12">
            <br/>
            <button class="btn btn-primary" id="saveAct" type="button">
                <b>{{ lang._('Apply') }}</b> <i id="saveAct_progress"></i>
            </button>
            <button class="btn btn-default" id="testAct" type="button">
                <b>{{ lang._('Save and send test notification') }}</b> <i id="testAct_progress"></i>
            </button>
            <br/><br/>
        </div>
    </div>
</section>
