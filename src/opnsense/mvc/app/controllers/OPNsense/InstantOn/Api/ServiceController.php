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

use OPNsense\Base\ApiMutableServiceControllerBase;
use OPNsense\Core\Backend;

class ServiceController extends ApiMutableServiceControllerBase
{
    protected static $internalServiceClass = '\OPNsense\InstantOn\InstantOn';
    protected static $internalServiceTemplate = 'OPNsense/InstantOn';
    protected static $internalServiceEnabled = 'general.enabled';
    protected static $internalServiceName = 'instanton';

    /**
     * Poll all sources now (asks the running monitor, or runs one poll).
     */
    public function refreshAction()
    {
        if (!$this->request->isPost()) {
            return ['status' => 'error', 'message' => 'POST required'];
        }
        $this->sessionClose();
        $response = trim((new Backend())->configdRun('instanton refresh'));
        return json_decode($response, true) ?? ['status' => 'error', 'message' => $response];
    }

    /**
     * Check the saved connection settings against the devices.
     */
    public function testAction()
    {
        if (!$this->request->isPost()) {
            return ['status' => 'error', 'message' => 'POST required'];
        }
        $this->sessionClose();
        $backend = new Backend();
        $backend->configdRun('template reload OPNsense/InstantOn');
        $response = trim($backend->configdRun('instanton test'));
        $result = json_decode($response, true);
        return is_array($result) ? ['status' => 'ok', 'result' => $result]
            : ['status' => 'error', 'message' => $response];
    }

    /**
     * List the sites of a saved cloud account (for the site selection).
     */
    public function cloudsitesAction($uuid = '')
    {
        if (!$this->request->isPost()) {
            return ['status' => 'error', 'message' => 'POST required'];
        }
        if (!preg_match('/^[A-Za-z0-9-]{1,64}$/', $uuid)) {
            return ['status' => 'error', 'message' => 'invalid account'];
        }
        $this->sessionClose();
        $backend = new Backend();
        $backend->configdRun('template reload OPNsense/InstantOn');
        $response = trim($backend->configdpRun('instanton cloudsites', [$uuid]));
        return json_decode($response, true) ?? ['status' => 'error', 'message' => $response];
    }
}
