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
 * Switch configuration: read sections for the editor and apply changes.
 * The backend validates every change, refuses the sections that control
 * access to the switch and records each change in the event history.
 */
class ConfigController extends ApiControllerBase
{
    private const ACTIONS = ['port', 'poe', 'poe_cycle', 'system', 'time', 'syslog', 'locate', 'cable_test',
        'reboot', 'section', 'save'];

    private function decode($response)
    {
        $data = json_decode($response, true);
        return is_array($data) ? $data : ['status' => 'error', 'message' => trim($response)];
    }

    /**
     * Read a group or section from a switch ("cached" returns the stored copy).
     */
    public function readAction($switch = '', $what = 'cached')
    {
        if ($what !== 'cached' && !$this->request->isPost()) {
            return ['status' => 'error', 'message' => 'POST required'];
        }
        if (!preg_match('/^[A-Za-z0-9_]{1,64}$/', $what) || !preg_match('/^[A-Za-z0-9_-]{1,64}$/', $switch)) {
            return ['status' => 'error', 'message' => 'invalid section'];
        }
        if (method_exists($this, 'sessionClose')) {
            $this->sessionClose();
        }
        return $this->decode((new Backend())->configdpRun('instanton readconfig', [$switch . ':' . $what]));
    }

    /**
     * Apply one change: POST request={"switch": <id>, "action": ..., "params": {...}}
     */
    public function applyAction()
    {
        if (!$this->request->isPost()) {
            return ['status' => 'error', 'message' => 'POST required'];
        }
        $request = json_decode((string)$this->request->getPost('request'), true);
        if (!is_array($request) || !in_array($request['action'] ?? '', self::ACTIONS, true)) {
            return ['status' => 'error', 'message' => 'invalid request'];
        }
        $switch = (string)($request['switch'] ?? '');
        if (!preg_match('/^[A-Za-z0-9-]{0,64}$/', $switch)) {
            return ['status' => 'error', 'message' => 'invalid switch'];
        }
        $payload = json_encode(['switch' => $switch, 'action' => $request['action'],
            'params' => $request['params'] ?? new \stdClass()]);
        if ($payload === false || strlen($payload) > 16384) {
            return ['status' => 'error', 'message' => 'request too large'];
        }
        if (method_exists($this, 'sessionClose')) {
            $this->sessionClose();
        }
        $arg = rtrim(strtr(base64_encode($payload), '+/', '-_'), '=');
        return $this->decode((new Backend())->configdpRun('instanton configure', [$arg]));
    }
}
