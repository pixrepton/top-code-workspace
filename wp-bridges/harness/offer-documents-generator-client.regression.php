<?php

if (PHP_SAPI !== 'cli') {
    fwrite(STDERR, "CLI only.\n");
    exit(1);
}

$scenario = null;
foreach ($argv as $arg) {
    if (strpos((string) $arg, '--scenario=') === 0) {
        $scenario = substr((string) $arg, 11);
        break;
    }
}

if ($scenario === null) {
    $scenarios = array(
        'default_endpoint',
        'endpoint_constant',
        'base_url_constant',
        'missing_endpoint',
        'missing_key',
        'invalid_json',
        'missing_download_url',
        'non_pdf_format',
        'success_pdf',
    );

    foreach ($scenarios as $name) {
        $command = escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg(__FILE__) . ' --scenario=' . escapeshellarg($name);
        passthru($command, $status);
        if ((int) $status !== 0) {
            exit((int) $status);
        }
    }
    exit(0);
}

define('ABSPATH', __DIR__);

$GLOBALS['topinstal_option_store'] = array();
$GLOBALS['topinstal_remote_post_calls'] = array();
$GLOBALS['topinstal_rest_do_request_calls'] = array();
$GLOBALS['topinstal_remote_post_handler'] = null;
$GLOBALS['topinstal_rest_do_request_handler'] = null;

if (!class_exists('WP_Error')) {
    class WP_Error {
        private $code;
        private $message;
        public function __construct($code = '', $message = '') { $this->code = $code; $this->message = $message; }
        public function get_error_code() { return $this->code; }
        public function get_error_message() { return $this->message; }
    }
}

if (!class_exists('WP_REST_Request')) {
    class WP_REST_Request {
        public $headers = array();
        public $body = '';
        public function __construct($method = 'POST', $route = '') {}
        public function set_header($name, $value) { $this->headers[(string) $name] = $value; }
        public function set_body($body) { $this->body = (string) $body; }
    }
}

function is_wp_error($value) { return $value instanceof WP_Error; }
function wp_remote_post($url, $args = array()) {
    $GLOBALS['topinstal_remote_post_calls'][] = array('url' => $url, 'args' => $args);
    if (is_callable($GLOBALS['topinstal_remote_post_handler'])) {
        return call_user_func($GLOBALS['topinstal_remote_post_handler'], $url, $args);
    }
    return array('response' => array('code' => 500), 'body' => '');
}
function wp_remote_retrieve_response_code($response) { return isset($response['response']['code']) ? (int) $response['response']['code'] : 0; }
function wp_remote_retrieve_body($response) { return isset($response['body']) ? (string) $response['body'] : ''; }
function wp_json_encode($value) { return json_encode($value); }
function rest_do_request($request) {
    $GLOBALS['topinstal_rest_do_request_calls'][] = $request;
    if (is_callable($GLOBALS['topinstal_rest_do_request_handler'])) {
        return call_user_func($GLOBALS['topinstal_rest_do_request_handler'], $request);
    }
    return new WP_Error('rest_not_stubbed', 'rest_do_request not stubbed');
}
function rest_url($path = '') { return 'https://example.com/wp-json/' . ltrim((string) $path, '/'); }
function get_site_url() { return 'https://example.com'; }
function untrailingslashit($value) { return rtrim((string) $value, '/'); }
function wp_parse_url($url) { return parse_url((string) $url); }
function wp_http_validate_url($url) { return filter_var((string) $url, FILTER_VALIDATE_URL) ? $url : false; }
function get_option($name, $default = '') { return array_key_exists($name, $GLOBALS['topinstal_option_store']) ? $GLOBALS['topinstal_option_store'][$name] : $default; }
function sanitize_key($key) { return preg_replace('/[^a-z0-9_\-]/', '', strtolower((string) $key)); }

require_once dirname(__DIR__) . '/mail-ingress/WorkflowConfig.php';
require_once dirname(__DIR__) . '/mail-ingress/OfferDocumentsGeneratorClient.php';

class OfferDocumentsGeneratorConfigDouble {
    private $endpoint;
    private $key;
    private $timeout;
    public function __construct($endpoint, $key, $timeout = 30) { $this->endpoint = (string) $endpoint; $this->key = (string) $key; $this->timeout = (int) $timeout; }
    public function resolve_generator_endpoint() { return array('value' => $this->endpoint, 'source' => 'double', 'sourceName' => 'harness', 'configType' => 'endpoint'); }
    public function resolve_generator_key() { return array('value' => $this->key, 'present' => trim($this->key) !== '', 'source' => 'double', 'sourceName' => 'harness'); }
    public function resolve_generator_timeout() { return array('value' => $this->timeout, 'source' => 'double', 'sourceName' => 'harness'); }
    public function get_generator_endpoint() { return $this->endpoint; }
    public function get_generator_key() { return $this->key; }
    public function get_generator_timeout() { return $this->timeout; }
    public function get_generator_route() { return '/wp-json/topinstal/v1/offer-documents/generate'; }
}

function assert_true($condition, $message) { if (!$condition) { throw new RuntimeException($message); } }
function assert_same($expected, $actual, $message) { if ($expected !== $actual) { throw new RuntimeException($message . ' expected=' . var_export($expected, true) . ' actual=' . var_export($actual, true)); } }

function run_generator_with_response($response) {
    $GLOBALS['topinstal_remote_post_handler'] = static function () use ($response) {
        return $response;
    };
    $client = new TopInstal_OfferDocumentsGeneratorClient(
        new OfferDocumentsGeneratorConfigDouble(
            'https://example.com/pdf/wp-json/topinstal/v1/offer-documents/generate',
            'secret-key',
            45
        )
    );
    return $client->generate(array('traceId' => 'trace-harness'), array('trace_id' => 'trace-harness'));
}

switch ($scenario) {
    case 'default_endpoint':
        $config = new TopInstal_MailIngressWorkflowConfig();
        $resolved = $config->resolve_generator_endpoint();
        assert_same('', $resolved['value'], 'repo default endpoint should stay empty when no override is set');
        assert_same('missing', $resolved['source'], 'repo default endpoint should report missing source');
        echo "[PASS] default_endpoint\n";
        break;

    case 'endpoint_constant':
        define('TOPINSTAL_AGENT_OFFER_DOCUMENTS_ENDPOINT', " https://www.topinstal.com.pl/pdf/wp-json/topinstal/v1/offer-documents/generate \n");
        $config = new TopInstal_MailIngressWorkflowConfig();
        $resolved = $config->resolve_generator_endpoint();
        assert_same('https://www.topinstal.com.pl/pdf/wp-json/topinstal/v1/offer-documents/generate', $resolved['value'], 'legacy endpoint constant should resolve verbatim');
        assert_same('endpoint', $resolved['configType'], 'endpoint constant should keep endpoint config type');
        echo "[PASS] endpoint_constant\n";
        break;

    case 'base_url_constant':
        define('TOPINSTAL_MAIL_INGRESS_GENERATOR_BASE_URL', " https://www.topinstal.com.pl/pdf/ \n");
        $config = new TopInstal_MailIngressWorkflowConfig();
        $resolved = $config->resolve_generator_endpoint();
        assert_same('https://www.topinstal.com.pl/pdf/wp-json/topinstal/v1/offer-documents/generate', $resolved['value'], 'base url constant should build canonical route');
        assert_same('base_url', $resolved['configType'], 'base url should report base_url config type');
        echo "[PASS] base_url_constant\n";
        break;

    case 'missing_endpoint':
        $client = new TopInstal_OfferDocumentsGeneratorClient(new OfferDocumentsGeneratorConfigDouble('', 'secret-key'));
        $result = $client->generate(array('traceId' => 'trace-harness'));
        assert_same('GENERATOR_ENDPOINT_MISSING', $result['error']['code'], 'missing endpoint should be classified');
        echo "[PASS] missing_endpoint\n";
        break;

    case 'missing_key':
        $client = new TopInstal_OfferDocumentsGeneratorClient(new OfferDocumentsGeneratorConfigDouble('https://example.com/pdf/wp-json/topinstal/v1/offer-documents/generate', ''));
        $result = $client->generate(array('traceId' => 'trace-harness'));
        assert_same('GENERATOR_KEY_MISSING', $result['error']['code'], 'missing key should be classified');
        echo "[PASS] missing_key\n";
        break;

    case 'invalid_json':
        $result = run_generator_with_response(array(
            'response' => array('code' => 200),
            'body' => '<html>bad gateway</html>',
        ));
        assert_same('GENERATOR_INVALID_JSON', $result['error']['code'], 'invalid json should be classified');
        assert_same(1, count($GLOBALS['topinstal_remote_post_calls']), 'external /pdf endpoint should use wp_remote_post');
        assert_same(0, count($GLOBALS['topinstal_rest_do_request_calls']), 'external /pdf endpoint must not use internal rest dispatch');
        echo "[PASS] invalid_json\n";
        break;

    case 'missing_download_url':
        $result = run_generator_with_response(array(
            'response' => array('code' => 200),
            'body' => json_encode(array(
                'traceId' => 'trace-harness',
                'status' => 'success',
                'document' => array(
                    'format' => 'pdf',
                    'filename' => 'offer.pdf',
                ),
                'warnings' => array(),
            )),
        ));
        assert_same('GENERATOR_DOWNLOAD_URL_MISSING', $result['error']['code'], 'missing download url should be classified');
        echo "[PASS] missing_download_url\n";
        break;

    case 'non_pdf_format':
        $result = run_generator_with_response(array(
            'response' => array('code' => 200),
            'body' => json_encode(array(
                'traceId' => 'trace-harness',
                'status' => 'success',
                'document' => array(
                    'format' => 'docx',
                    'filename' => 'offer.docx',
                    'downloadUrl' => 'https://example.com/offer.docx',
                ),
                'warnings' => array(),
            )),
        ));
        assert_same('GENERATOR_FORMAT_NOT_PDF', $result['error']['code'], 'non-pdf format should be classified');
        echo "[PASS] non_pdf_format\n";
        break;

    case 'success_pdf':
        $result = run_generator_with_response(array(
            'response' => array('code' => 200),
            'body' => json_encode(array(
                'traceId' => 'trace-harness',
                'status' => 'success',
                'document' => array(
                    'format' => 'pdf',
                    'filename' => 'offer.pdf',
                    'downloadUrl' => 'https://example.com/offer.pdf',
                    'mimeType' => 'application/pdf',
                ),
                'warnings' => array(array('code' => 'MAPPED_FROM_OFFER_DTO')),
            )),
        ));
        assert_true(!empty($result['ok']), 'success response should stay ok');
        assert_same('https://example.com/offer.pdf', $result['document']['downloadUrl'], 'download url should be preserved');
        assert_same(1, count($result['warnings']), 'warnings should be preserved');
        echo "[PASS] success_pdf\n";
        break;

    default:
        throw new RuntimeException('Unknown scenario: ' . $scenario);
}
