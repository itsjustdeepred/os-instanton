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
     * The monitor needs at least one enabled source.
     */
    public function performValidation($validateFullModel = false)
    {
        $messages = parent::performValidation($validateFullModel);
        if ((string)$this->general->enabled !== '1') {
            return $messages;
        }
        $sources = (string)$this->aps->enabled === '1' ? 1 : 0;
        foreach ($this->switches->switch->iterateItems() as $switch) {
            $sources += (string)$switch->enabled === '1' ? 1 : 0;
        }
        foreach ($this->clouds->account->iterateItems() as $account) {
            $sources += (string)$account->enabled === '1' ? 1 : 0;
        }
        if ($sources === 0) {
            $messages->appendMessage(new Message(
                gettext('Enable at least one data source: a switch, the access points or a cloud account.'),
                'general.enabled'
            ));
        }
        return $messages;
    }
}
