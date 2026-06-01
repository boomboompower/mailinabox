<?php
/***********************************************
* File      :   config.php
* Project   :   Z-Push
* Descr     :   IMAP backend configuration file
************************************************/

define('IMAP_SERVER', '127.0.0.1');
define('IMAP_PORT', 993);
define('IMAP_OPTIONS', '/ssl/norsh/novalidate-cert');
define('IMAP_DEFAULTFROM', 'username');

define('SYSTEM_MIME_TYPES_MAPPING', '/etc/mime.types');
define('IMAP_AUTOSEEN_ON_DELETE', false);
define('IMAP_FOLDER_CONFIGURED', true);
define('IMAP_FOLDER_PREFIX', '');
define('IMAP_FOLDER_PREFIX_IN_INBOX', false);
// see our conf/dovecot-mailboxes.conf file for IMAP special flags settings
define('IMAP_FOLDER_INBOX', 'INBOX');
define('IMAP_FOLDER_SENT', 'SENT');
define('IMAP_FOLDER_DRAFT', 'DRAFTS');
define('IMAP_FOLDER_TRASH', 'TRASH');
define('IMAP_FOLDER_SPAM', 'SPAM');
define('IMAP_FOLDER_ARCHIVE', 'ARCHIVE');

define('IMAP_INLINE_FORWARD', true);
define('IMAP_EXCLUDED_FOLDERS', '');

define('IMAP_SMTP_METHOD', 'sendmail');

global $imap_smtp_params;
$imap_smtp_params = array('host' => 'ssl://127.0.0.1', 'port' => 465, 'auth' => true, 'username' => 'imap_username', 'password' => 'imap_password');

define('MAIL_MIMEPART_CRLF', "\r\n");
define('IMAP_MEETING_USE_CALDAV', false);

?>
