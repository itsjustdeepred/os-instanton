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

namespace OPNsense\InstantOn\Api;

use OPNsense\Base\ApiMutableModelControllerBase;

class SettingsController extends ApiMutableModelControllerBase
{
    protected static $internalModelName = 'instanton';
    protected static $internalModelClass = 'OPNsense\InstantOn\InstantOn';

    /* switches */

    public function searchSwitchAction()
    {
        return $this->searchBase('switches.switch', ['enabled', 'name', 'host', 'username', 'uplink_ports'], 'name');
    }

    public function getSwitchAction($uuid = null)
    {
        return $this->getBase('switch', 'switches.switch', $uuid);
    }

    public function addSwitchAction()
    {
        return $this->addBase('switch', 'switches.switch');
    }

    public function setSwitchAction($uuid)
    {
        return $this->setBase('switch', 'switches.switch', $uuid);
    }

    public function delSwitchAction($uuid)
    {
        return $this->delBase('switches.switch', $uuid);
    }

    public function toggleSwitchAction($uuid, $enabled = null)
    {
        return $this->toggleBase('switches.switch', $uuid, $enabled);
    }

    /* cloud accounts */

    public function searchAccountAction()
    {
        return $this->searchBase('clouds.account', ['enabled', 'name', 'username', 'sites'], 'name');
    }

    public function getAccountAction($uuid = null)
    {
        return $this->getBase('account', 'clouds.account', $uuid);
    }

    public function addAccountAction()
    {
        return $this->addBase('account', 'clouds.account');
    }

    public function setAccountAction($uuid)
    {
        return $this->setBase('account', 'clouds.account', $uuid);
    }

    public function delAccountAction($uuid)
    {
        return $this->delBase('clouds.account', $uuid);
    }

    public function toggleAccountAction($uuid, $enabled = null)
    {
        return $this->toggleBase('clouds.account', $uuid, $enabled);
    }
}
