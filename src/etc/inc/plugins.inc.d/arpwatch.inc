<?php

/*
 * ARPWatch plugin hooks
 * SPDX-License-Identifier: BSD-2-Clause
 */

function arpwatch_enabled()
{
    global $config;

    return isset($config['OPNsense']['arpwatch']['general']['enabled']) &&
        $config['OPNsense']['arpwatch']['general']['enabled'] == 1;
}

function arpwatch_services()
{
    $services = [];

    if (arpwatch_enabled()) {
        $services[] = [
            'description' => gettext('ARPWatch new device monitor'),
            'configd' => [
                'restart' => ['arpwatch restart'],
                'start' => ['arpwatch start'],
                'stop' => ['arpwatch stop'],
            ],
            'pidfile' => '/var/run/arpwatchd.pid',
            'name' => 'arpwatch',
        ];
    }

    return $services;
}

function arpwatch_syslog()
{
    return ['arpwatch' => ['facility' => ['arpwatch']]];
}
