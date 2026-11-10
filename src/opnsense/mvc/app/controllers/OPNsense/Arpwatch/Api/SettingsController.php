<?php

/*
 * ARPWatch plugin settings API
 * SPDX-License-Identifier: BSD-2-Clause
 */

namespace OPNsense\Arpwatch\Api;

use OPNsense\Base\ApiMutableModelControllerBase;

class SettingsController extends ApiMutableModelControllerBase
{
    protected static $internalModelName = 'arpwatch';
    protected static $internalModelClass = 'OPNsense\Arpwatch\Arpwatch';
}
