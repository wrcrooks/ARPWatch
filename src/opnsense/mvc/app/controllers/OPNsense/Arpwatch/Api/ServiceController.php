<?php

/*
 * ARPWatch plugin service API
 * SPDX-License-Identifier: BSD-2-Clause
 */

namespace OPNsense\Arpwatch\Api;

use OPNsense\Base\ApiMutableServiceControllerBase;
use OPNsense\Core\Backend;

class ServiceController extends ApiMutableServiceControllerBase
{
    protected static $internalServiceClass = '\OPNsense\Arpwatch\Arpwatch';
    protected static $internalServiceTemplate = 'OPNsense/Arpwatch';
    protected static $internalServiceEnabled = 'general.enabled';
    protected static $internalServiceName = 'arpwatch';

    /**
     * send a test message using the saved settings of every enabled notification method
     */
    public function testAction()
    {
        if (!$this->request->isPost()) {
            return ['status' => 'failed', 'results' => []];
        }
        $backend = new Backend();
        $backend->configdRun('template reload OPNsense/Arpwatch');
        $response = json_decode((string)$backend->configdRun('arpwatch test'), true);
        if (!is_array($response)) {
            return ['status' => 'failed', 'results' => []];
        }
        return $response;
    }
}
