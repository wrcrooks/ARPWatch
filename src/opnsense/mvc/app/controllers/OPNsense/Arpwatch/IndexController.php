<?php

/*
 * ARPWatch plugin UI controller
 * SPDX-License-Identifier: BSD-2-Clause
 */

namespace OPNsense\Arpwatch;

class IndexController extends \OPNsense\Base\IndexController
{
    public function indexAction()
    {
        $this->view->generalForm = $this->getForm('general');
        $this->view->notificationsForm = $this->getForm('notifications');
        $this->view->pick('OPNsense/Arpwatch/index');
    }
}
