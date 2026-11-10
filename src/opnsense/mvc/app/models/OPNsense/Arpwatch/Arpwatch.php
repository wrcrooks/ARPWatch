<?php

/*
 * ARPWatch plugin model
 * SPDX-License-Identifier: BSD-2-Clause
 */

namespace OPNsense\Arpwatch;

use OPNsense\Base\BaseModel;
use OPNsense\Base\Messages\Message;

class Arpwatch extends BaseModel
{
    /**
     * {@inheritdoc}
     */
    public function performValidation($validateFullModel = false)
    {
        $messages = parent::performValidation($validateFullModel);

        // values end up in an ini style file, one per line
        foreach ($this->getFlatNodes() as $key => $node) {
            if (preg_match('/[\r\n]/', (string)$node)) {
                $messages->appendMessage(new Message(gettext('Line breaks are not allowed.'), $key));
            }
        }

        foreach (array_filter(explode(',', (string)$this->general->ignore_macs)) as $prefix) {
            if (!preg_match('/^[0-9a-f]{2}(:[0-9a-f]{2}){0,5}$/i', $prefix)) {
                $messages->appendMessage(new Message(
                    sprintf(gettext('"%s" is not a MAC address or prefix (e.g. 00:11:22 or 00:11:22:33:44:55).'), $prefix),
                    'general.ignore_macs'
                ));
            }
        }

        $notify = $this->notifications;
        $recipients = array_filter(explode(',', (string)$notify->smtp_to));
        foreach ($recipients as $recipient) {
            if (filter_var($recipient, FILTER_VALIDATE_EMAIL) === false) {
                $messages->appendMessage(new Message(
                    sprintf(gettext('"%s" is not a valid email address.'), $recipient),
                    'notifications.smtp_to'
                ));
            }
        }

        $required = [];
        if ((string)$notify->smtp_enabled == '1') {
            $required['smtp_host'] = gettext('A mail server is required when SMTP notifications are enabled.');
            $required['smtp_from'] = gettext('A sender address is required when SMTP notifications are enabled.');
            $required['smtp_to'] = gettext('At least one recipient is required when SMTP notifications are enabled.');
        }
        if ((string)$notify->telegram_enabled == '1') {
            $required['telegram_token'] = gettext('A bot token is required when Telegram notifications are enabled.');
            $required['telegram_chat_id'] = gettext('A chat id is required when Telegram notifications are enabled.');
        }
        if ((string)$notify->pushbullet_enabled == '1') {
            $required['pushbullet_token'] = gettext('An access token is required when Pushbullet notifications are enabled.');
        }
        foreach ($required as $field => $text) {
            if ((string)$notify->$field === '') {
                $messages->appendMessage(new Message($text, 'notifications.' . $field));
            }
        }

        return $messages;
    }
}
