<?php

/*
 * ARPWatch plugin device database API
 * SPDX-License-Identifier: BSD-2-Clause
 */

namespace OPNsense\Arpwatch\Api;

use OPNsense\Base\ApiControllerBase;
use OPNsense\Core\Backend;

class HostsController extends ApiControllerBase
{
    /**
     * list known devices
     */
    public function searchAction()
    {
        $data = json_decode((string)(new Backend())->configdRun('arpwatch list'), true);
        $rows = is_array($data) && isset($data['rows']) ? $data['rows'] : [];
        return $this->searchRecordsetBase($rows);
    }

    /**
     * forget a device, it will be reported as new when it shows up again
     * @param string $id mac address without separators
     */
    public function delAction($id)
    {
        $id = strtolower((string)$id);
        if ($this->request->isPost() && preg_match('/^[0-9a-f]{12}$/', $id)) {
            $response = trim((string)(new Backend())->configdpRun('arpwatch delete', [$id]));
            return ['result' => $response == 'OK' ? 'deleted' : 'not found'];
        }
        return ['result' => 'failed'];
    }

    /**
     * forget all devices
     */
    public function flushAction()
    {
        if ($this->request->isPost()) {
            $response = trim((string)(new Backend())->configdRun('arpwatch flush'));
            return ['result' => $response == 'OK' ? 'ok' : 'failed'];
        }
        return ['result' => 'failed'];
    }
}
