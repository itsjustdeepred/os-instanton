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
 * Read-only access to the data collected by the monitor.
 */
class StatusController extends ApiControllerBase
{
    private function view($name, $switch = '')
    {
        if ($switch !== '' && $switch !== null) {
            if (!preg_match('/^[A-Za-z0-9-]{1,64}$/', $switch)) {
                return ['error' => 'invalid switch id'];
            }
            $name .= ':' . $switch;
        }
        $this->sessionClose();
        $response = (new Backend())->configdpRun('instanton view', [$name]);
        $data = json_decode($response, true);
        if (!is_array($data)) {
            return ['error' => gettext('No data available from the monitor backend.'), 'raw' => trim($response)];
        }
        return $data;
    }

    public function summaryAction()
    {
        return $this->view('summary');
    }

    public function switchAction($id = '')
    {
        return $this->view('switch', $id);
    }

    public function portsAction($id = '')
    {
        return $this->view('ports', $id);
    }

    public function apsAction()
    {
        return $this->view('aps');
    }

    public function clientsAction()
    {
        return $this->view('clients');
    }

    public function eventsAction()
    {
        return $this->view('events');
    }

    public function logAction($id = '')
    {
        return $this->view('log', $id);
    }

    public function insightsAction()
    {
        return $this->view('insights');
    }

    public function topologyAction()
    {
        return $this->view('topology');
    }
}
