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

use OPNsense\Base\BaseModel;
use OPNsense\Base\Messages\Message;

class InstantOn extends BaseModel
{
    /**
     * Credentials are only mandatory for the sources that are switched on.
     */
    public function performValidation($validateFullModel = false)
    {
        $messages = parent::performValidation($validateFullModel);
        if ((string)$this->general->enabled !== '1') {
            return $messages;
        }
        if ((string)$this->switch->enabled === '1') {
            foreach (['host', 'username', 'password'] as $field) {
                if ((string)$this->switch->$field === '') {
                    $messages->appendMessage(new Message(
                        gettext('Required while the switch source is enabled.'),
                        'switch.' . $field
                    ));
                }
            }
        }
        if ((string)$this->cloud->enabled === '1') {
            foreach (['username', 'password'] as $field) {
                if ((string)$this->cloud->$field === '') {
                    $messages->appendMessage(new Message(
                        gettext('Required while the cloud source is enabled.'),
                        'cloud.' . $field
                    ));
                }
            }
        }
        if (
            (string)$this->switch->enabled !== '1' &&
            (string)$this->aps->enabled !== '1' &&
            (string)$this->cloud->enabled !== '1'
        ) {
            $messages->appendMessage(new Message(
                gettext('Enable at least one data source.'),
                'general.enabled'
            ));
        }
        return $messages;
    }
}
