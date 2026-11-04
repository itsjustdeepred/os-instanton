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

use OPNsense\Base\ApiControllerBase;
use OPNsense\Core\Backend;

/**
 * Wi-Fi networks of an Instant On site, through the cloud account set up in the settings.
 */
class CloudController extends ApiControllerBase
{
    private function run($request)
    {
        if (method_exists($this, 'sessionClose')) {
            $this->sessionClose();
        }
        $payload = json_encode($request);
        if ($payload === false || strlen($payload) > 16384) {
            return ['status' => 'error', 'message' => 'request too large'];
        }
        $arg = rtrim(strtr(base64_encode($payload), '+/', '-_'), '=');
        $response = trim((new Backend())->configdpRun('instanton cloudnet', [$arg]));
        return json_decode($response, true) ?? ['status' => 'error', 'message' => $response];
    }

    private function ids($account, $site)
    {
        return preg_match('/^[A-Za-z0-9-]{1,64}$/', $account) && preg_match('/^[A-Za-z0-9-]{1,64}$/', $site);
    }

    public function networksAction($account = '', $site = '')
    {
        if (!$this->ids($account, $site)) {
            return ['status' => 'error', 'message' => 'invalid site'];
        }
        return $this->run(['op' => 'list', 'account' => $account, 'site' => $site]);
    }

    /**
     * POST network (JSON object), id for an existing network.
     */
    public function saveAction($account = '', $site = '')
    {
        if (!$this->request->isPost() || !$this->ids($account, $site)) {
            return ['status' => 'error', 'message' => 'invalid request'];
        }
        $network = json_decode((string)$this->request->getPost('network'), true);
        if (!is_array($network)) {
            return ['status' => 'error', 'message' => 'invalid network'];
        }
        return $this->run(['op' => 'save', 'account' => $account, 'site' => $site,
            'id' => (string)$this->request->getPost('id'), 'network' => $network]);
    }

    public function deleteAction($account = '', $site = '', $id = '')
    {
        if (!$this->request->isPost() || !$this->ids($account, $site) || !preg_match('/^[A-Za-z0-9-]{1,64}$/', $id)) {
            return ['status' => 'error', 'message' => 'invalid request'];
        }
        return $this->run(['op' => 'delete', 'account' => $account, 'site' => $site, 'id' => $id]);
    }
}
