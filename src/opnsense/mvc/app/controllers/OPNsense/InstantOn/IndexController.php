<?php

/*
 * Copyright (C) 2026 os-instanton contributors
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 * 1. Redistributions of source code must retain the above copyright notice,
 *    this list of conditions and the following disclaimer.
 *
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED ``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES,
 * INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY
 * AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
 * AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
 * OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 * SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 * INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 * CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 * ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 */

namespace OPNsense\InstantOn;

class IndexController extends \OPNsense\Base\IndexController
{
    public function indexAction()
    {
        $this->view->pick('OPNsense/InstantOn/overview');
    }

    public function switchAction()
    {
        $this->view->pick('OPNsense/InstantOn/switch');
    }

    public function accesspointsAction()
    {
        $this->view->pick('OPNsense/InstantOn/accesspoints');
    }

    public function clientsAction()
    {
        $this->view->pick('OPNsense/InstantOn/clients');
    }

    public function eventsAction()
    {
        $this->view->pick('OPNsense/InstantOn/events');
    }

    public function mapAction()
    {
        $this->view->pick('OPNsense/InstantOn/map');
    }

    public function configurationAction()
    {
        $this->view->pick('OPNsense/InstantOn/configuration');
    }

    public function settingsAction()
    {
        $this->view->settingsForm = $this->getForm('settings');
        $this->view->switchForm = $this->getForm('dialogSwitch');
        $this->view->accountForm = $this->getForm('dialogCloud');
        $this->view->pick('OPNsense/InstantOn/settings');
    }
}
