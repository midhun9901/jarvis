# FAU Mail Agent

A minimal Chrome extension agent for FAUmail that accepts one command and tries to complete the whole inbox workflow.

## Current workflow

- Open FAUmail
- Detect whether the page is a Roundcube login or inbox
- Optionally submit saved credentials
- Wait for inbox
- Summarize visible inbox messages locally

## Supported commands

- `check my mails`
- `login and check mails`
- `summarize inbox`
- `open inbox`
- `open unread`

## Jarvis voice bridge

Once this extension is loaded and the Jarvis page is refreshed, you can say commands such as:

- `check my college mails`
- `open my college inbox`
- `open my latest college mail`

Jarvis will hand the task to this extension and speak the result back.

## Load it in Chrome

1. Open `chrome://extensions`
2. Enable `Developer mode`
3. Click `Load unpacked`
4. Select this folder:
   `C:\PROJECTS\jarvis\extensions\chrome\fau-mail-agent`
5. Refresh the Jarvis page after loading or updating the extension so the page bridge can attach

## Save credentials

1. Open the extension
2. Click `Credentials`
3. Save your FAUmail username and password

This stores credentials in local Chrome extension storage on this machine.

## Notes

- This targets a Roundcube-style FAUmail page.
- If SSO, MFA, or CAPTCHA appears, you may need to complete that manually and run the command again.
- Inbox summarization is local and does not us
]e API tokens.
