<?php

if (!defined('ABSPATH')) {
    exit;
}

if (!class_exists('TopInstal_OfferDocumentsGeneratorClient')) {
    class TopInstal_OfferDocumentsGeneratorClient {
        const REQUEST_MODE = 'from-offer-dto';
        const DOCUMENT_TYPE = 'offer_document';
        const OUTPUT_FORMAT = 'pdf';

        private $config;

        public function __construct($config = null) {
            $this->config = $config ?: new TopInstal_MailIngressWorkflowConfig();
        }

        public function generate($offer_dto, $context = array()) {
            $trace_id = $this->resolve_trace_id($context, $offer_dto);
            $endpoint_resolution = $this->resolve_config_bundle('resolve_generator_endpoint', 'get_generator_endpoint', array(
                'value' => '',
                'source' => 'unknown',
                'sourceName' => '',
                'configType' => 'unknown',
            ));
            $key_resolution = $this->resolve_config_bundle('resolve_generator_key', 'get_generator_key', array(
                'value' => '',
                'present' => false,
                'source' => 'unknown',
                'sourceName' => '',
            ));
            $timeout_resolution = $this->resolve_config_bundle('resolve_generator_timeout', 'get_generator_timeout', array(
                'value' => 120,
                'source' => 'unknown',
                'sourceName' => '',
            ));

            $endpoint = $this->normalize_url_string(isset($endpoint_resolution['value']) ? $endpoint_resolution['value'] : '');
            $key = trim((string) (isset($key_resolution['value']) ? $key_resolution['value'] : ''));
            $timeout_seconds = max(5, (int) (isset($timeout_resolution['value']) ? $timeout_resolution['value'] : 120));

            $request_context = array(
                'traceId' => $trace_id,
                'endpoint' => $endpoint,
                'endpointSource' => $this->describe_resolution_source($endpoint_resolution),
                'endpointConfigType' => isset($endpoint_resolution['configType']) ? (string) $endpoint_resolution['configType'] : 'unknown',
                'keyPresent' => $key !== '',
                'keySource' => $this->describe_resolution_source($key_resolution),
                'timeoutSeconds' => $timeout_seconds,
                'timeoutSource' => $this->describe_resolution_source($timeout_resolution),
                'requestMode' => self::REQUEST_MODE,
                'documentType' => self::DOCUMENT_TYPE,
                'outputFormat' => self::OUTPUT_FORMAT,
            );

            if ($endpoint === '') {
                return $this->finalize_error(
                    $this->build_error_result(
                        'GENERATOR_ENDPOINT_MISSING',
                        'Generator endpoint is not configured.',
                        $this->build_error_details($request_context, array(
                            'reason' => 'missing_endpoint',
                        )),
                        500,
                        false,
                        $trace_id
                    ),
                    $request_context
                );
            }

            if ($key === '') {
                return $this->finalize_error(
                    $this->build_error_result(
                        'GENERATOR_KEY_MISSING',
                        'Generator key is not configured.',
                        $this->build_error_details($request_context, array(
                            'reason' => 'missing_key',
                        )),
                        500,
                        false,
                        $trace_id
                    ),
                    $request_context
                );
            }

            if (!$this->is_valid_url($endpoint)) {
                return $this->finalize_error(
                    $this->build_error_result(
                        'GENERATOR_INVALID_URL',
                        'Generator endpoint is not a valid URL.',
                        $this->build_error_details($request_context, array(
                            'reason' => 'invalid_endpoint_url',
                        )),
                        500,
                        false,
                        $trace_id
                    ),
                    $request_context
                );
            }

            $generator_context = array(
                'source' => isset($context['source']) && is_string($context['source']) && trim($context['source']) !== ''
                    ? trim((string) $context['source'])
                    : 'mail-ingress',
                'workflow' => isset($context['workflow']) && is_string($context['workflow']) && trim($context['workflow']) !== ''
                    ? trim((string) $context['workflow'])
                    : 'mail_ingress_offer_review',
                'channel' => isset($context['channel']) && is_string($context['channel']) && trim($context['channel']) !== ''
                    ? trim((string) $context['channel'])
                    : '',
                'leadId' => isset($context['lead_id']) ? (string) $context['lead_id'] : '',
                'requestId' => isset($context['request_id']) ? (string) $context['request_id'] : '',
                'messageId' => isset($context['message_id']) ? (string) $context['message_id'] : '',
            );
            if (isset($context['document_mode']) && is_string($context['document_mode']) && trim($context['document_mode']) !== '') {
                $generator_context['documentMode'] = trim((string) $context['document_mode']);
            }
            if (isset($context['generated_at']) && is_string($context['generated_at']) && trim($context['generated_at']) !== '') {
                $generator_context['generatedAt'] = trim((string) $context['generated_at']);
            }
            if (isset($context['machine_room_snapshot']) && is_array($context['machine_room_snapshot'])) {
                $generator_context['machineRoomSnapshot'] = $context['machine_room_snapshot'];
            }

            $payload = array(
                'schemaVersion' => '1.0',
                'traceId' => $trace_id,
                'mode' => self::REQUEST_MODE,
                'documentType' => self::DOCUMENT_TYPE,
                'outputFormat' => self::OUTPUT_FORMAT,
                'offerDto' => $offer_dto,
                'context' => $generator_context,
            );

            $this->log_generator_event('info', 'offer document generator request started', $request_context);
            $response = $this->dispatch_generator_request($endpoint, $key, $payload, $timeout_seconds);
            $transport_context = array_merge($request_context, array(
                'dispatchMode' => isset($response['dispatch_mode']) ? (string) $response['dispatch_mode'] : 'external',
                'httpStatus' => isset($response['status']) ? (int) $response['status'] : 0,
                'responseParseResult' => isset($response['body_state']) ? (string) $response['body_state'] : 'unknown',
            ));

            if (!empty($response['wp_error'])) {
                return $this->finalize_error(
                    $this->classify_wp_error($response['wp_error'], $trace_id, $transport_context),
                    $transport_context
                );
            }

            $status = isset($response['status']) ? (int) $response['status'] : 0;
            if ($status < 200 || $status >= 300) {
                return $this->finalize_error(
                    $this->classify_http_error($status, isset($response['body']) ? $response['body'] : null, $trace_id, $transport_context),
                    $transport_context
                );
            }

            $body_state = isset($response['body_state']) ? (string) $response['body_state'] : 'unknown';
            if ($body_state === 'empty') {
                return $this->finalize_error(
                    $this->build_error_result(
                        'GENERATOR_EMPTY_RESPONSE_BODY',
                        'Generator returned an empty response body.',
                        $this->build_error_details($transport_context, array(
                            'reason' => 'empty_response_body',
                        )),
                        502,
                        true,
                        $trace_id
                    ),
                    $transport_context
                );
            }

            if ($body_state === 'invalid_json') {
                return $this->finalize_error(
                    $this->build_error_result(
                        'GENERATOR_INVALID_JSON',
                        'Generator returned invalid JSON response.',
                        $this->build_error_details($transport_context, array(
                            'reason' => 'invalid_json_response',
                        )),
                        502,
                        true,
                        $trace_id
                    ),
                    $transport_context
                );
            }

            $result = $this->validate_success_response(
                isset($response['body']) ? $response['body'] : null,
                $trace_id,
                $transport_context
            );
            if (empty($result['ok'])) {
                return $this->finalize_error($result, $transport_context);
            }

            $this->log_generator_event('info', 'offer document generator request succeeded', array_merge(
                $transport_context,
                array(
                    'responseTraceId' => isset($result['traceId']) ? (string) $result['traceId'] : $trace_id,
                    'responseStatusField' => 'success',
                    'warningCount' => isset($result['warnings']) && is_array($result['warnings']) ? count($result['warnings']) : 0,
                    'downloadUrlPresent' => true,
                )
            ));

            return $result;
        }

        /**
         * @param string $endpoint
         * @param string $key
         * @param array<string,mixed> $payload
         * @param int $timeout_seconds
         * @return array<string,mixed>
         */
        private function dispatch_generator_request($endpoint, $key, $payload, $timeout_seconds) {
            if ($this->should_use_internal_rest_dispatch($endpoint)) {
                $response = $this->dispatch_internal_rest_request($key, $payload);
                $response['dispatch_mode'] = 'internal';
                return $response;
            }

            $encoded_payload = function_exists('wp_json_encode')
                ? wp_json_encode($payload)
                : json_encode($payload);
            if (!is_string($encoded_payload) || trim($encoded_payload) === '') {
                return array(
                    'dispatch_mode' => 'external',
                    'wp_error' => $this->create_wp_error(
                        'generator_json_encode_failed',
                        'Generator payload could not be JSON encoded.'
                    ),
                );
            }

            $response = wp_remote_post($endpoint, array(
                'timeout' => $timeout_seconds,
                'headers' => array(
                    'Content-Type' => 'application/json',
                    'Accept' => 'application/json',
                    'X-Top-Instal-Agent-Key' => $key,
                    'Authorization' => 'Bearer ' . $key,
                ),
                'body' => $encoded_payload,
            ));

            if (is_wp_error($response)) {
                return array(
                    'dispatch_mode' => 'external',
                    'wp_error' => $response,
                );
            }

            $parsed = $this->parse_http_response($response);
            $parsed['dispatch_mode'] = 'external';
            return $parsed;
        }

        /**
         * Avoid deadlocks on local single-process WP runtimes by dispatching the
         * generator REST route in-process only when the configured endpoint matches
         * the current instance exactly.
         *
         * @param string $endpoint
         * @return bool
         */
        private function should_use_internal_rest_dispatch($endpoint) {
            if (
                !function_exists('rest_do_request') ||
                !class_exists('WP_REST_Request') ||
                !function_exists('rest_url')
            ) {
                return false;
            }

            $candidate = $this->normalize_url_string($endpoint);
            if ($candidate === '') {
                return false;
            }

            $expected = array(
                (string) rest_url('topinstal/v1/offer-documents/generate'),
            );

            if (function_exists('get_site_url')) {
                $expected[] = untrailingslashit((string) get_site_url()) . $this->get_generator_route();
            }

            foreach ($expected as $url) {
                if ($this->urls_match($candidate, $url)) {
                    return true;
                }
            }

            return false;
        }

        /**
         * @param string $key
         * @param array<string,mixed> $payload
         * @return array<string,mixed>
         */
        private function dispatch_internal_rest_request($key, $payload) {
            try {
                $encoded_payload = function_exists('wp_json_encode')
                    ? wp_json_encode($payload)
                    : json_encode($payload);
                if (!is_string($encoded_payload) || trim($encoded_payload) === '') {
                    return array(
                        'wp_error' => $this->create_wp_error(
                            'generator_json_encode_failed',
                            'Generator payload could not be JSON encoded.'
                        ),
                    );
                }

                $request = new WP_REST_Request('POST', '/topinstal/v1/offer-documents/generate');
                $request->set_header('content-type', 'application/json');
                $request->set_header('accept', 'application/json');
                if ($key !== '') {
                    $request->set_header('x-top-instal-agent-key', $key);
                    $request->set_header('authorization', 'Bearer ' . $key);
                }
                $request->set_body($encoded_payload);

                $response = rest_do_request($request);
                if (is_wp_error($response)) {
                    return array('wp_error' => $response);
                }

                if (is_object($response) && method_exists($response, 'get_status') && method_exists($response, 'get_data')) {
                    return array(
                        'status' => (int) $response->get_status(),
                        'body' => $response->get_data(),
                        'body_state' => 'json',
                    );
                }

                return array(
                    'status' => 500,
                    'body' => array(
                        'errorCode' => 'GENERATOR_INTERNAL_DISPATCH_INVALID_RESPONSE',
                        'message' => 'Internal generator dispatch returned an invalid response.',
                    ),
                    'body_state' => 'json',
                );
            } catch (Throwable $e) {
                return array(
                    'wp_error' => $this->create_wp_error(
                        'generator_internal_dispatch_failed',
                        $e->getMessage()
                    ),
                );
            }
        }

        /**
         * @param mixed $response
         * @return array<string,mixed>
         */
        private function parse_http_response($response) {
            $status = (int) wp_remote_retrieve_response_code($response);
            $raw_body = (string) wp_remote_retrieve_body($response);
            $normalized_body = is_string($raw_body) ? trim(preg_replace('/^\xEF\xBB\xBF/', '', $raw_body)) : '';
            if ($normalized_body === '') {
                return array(
                    'status' => $status,
                    'body' => null,
                    'body_state' => 'empty',
                );
            }

            $decoded = json_decode($normalized_body, true);
            if (json_last_error() !== JSON_ERROR_NONE) {
                return array(
                    'status' => $status,
                    'body' => null,
                    'body_state' => 'invalid_json',
                );
            }

            return array(
                'status' => $status,
                'body' => $decoded,
                'body_state' => 'json',
            );
        }

        /**
         * @param mixed $decoded
         * @param string $trace_id
         * @param array<string,mixed> $transport_context
         * @return array<string,mixed>
         */
        private function validate_success_response($decoded, $trace_id, $transport_context) {
            if (!is_array($decoded)) {
                return $this->build_error_result(
                    'GENERATOR_RESPONSE_SHAPE_MISMATCH',
                    'Generator response JSON has an invalid shape.',
                    $this->build_error_details($transport_context, array(
                        'reason' => 'response_not_object',
                    )),
                    502,
                    true,
                    $trace_id
                );
            }

            $response_trace_id = $this->resolve_response_trace_id($decoded, $trace_id);
            $status_field = isset($decoded['status']) ? strtolower(trim((string) $decoded['status'])) : '';
            if ($status_field !== 'success') {
                return $this->build_error_result(
                    'GENERATOR_RESPONSE_STATUS_INVALID',
                    'Generator response status is not success.',
                    $this->build_error_details($transport_context, array(
                        'reason' => 'response_status_invalid',
                        'responseStatusField' => $status_field,
                    )),
                    502,
                    true,
                    $response_trace_id
                );
            }

            if (!isset($decoded['document']) || !is_array($decoded['document'])) {
                return $this->build_error_result(
                    'GENERATOR_RESPONSE_SHAPE_MISMATCH',
                    'Generator response is missing document payload.',
                    $this->build_error_details($transport_context, array(
                        'reason' => 'document_missing',
                        'responseStatusField' => $status_field,
                    )),
                    502,
                    true,
                    $response_trace_id
                );
            }

            $document = $decoded['document'];
            $format = isset($document['format']) ? strtolower(trim((string) $document['format'])) : '';
            if ($format !== self::OUTPUT_FORMAT) {
                return $this->build_error_result(
                    'GENERATOR_FORMAT_NOT_PDF',
                    'Generator returned a non-PDF document.',
                    $this->build_error_details($transport_context, array(
                        'reason' => 'document_format_not_pdf',
                        'responseStatusField' => $status_field,
                        'documentFormat' => $format,
                    )),
                    502,
                    true,
                    $response_trace_id
                );
            }

            $download_url = isset($document['downloadUrl']) ? trim((string) $document['downloadUrl']) : '';
            if ($download_url === '') {
                return $this->build_error_result(
                    'GENERATOR_DOWNLOAD_URL_MISSING',
                    'Generator did not return document.downloadUrl.',
                    $this->build_error_details($transport_context, array(
                        'reason' => 'document_download_url_missing',
                        'responseStatusField' => $status_field,
                    )),
                    502,
                    true,
                    $response_trace_id
                );
            }

            return array(
                'ok' => true,
                'document' => array(
                    'format' => self::OUTPUT_FORMAT,
                    'filename' => isset($document['filename']) ? (string) $document['filename'] : '',
                    'downloadUrl' => $download_url,
                    'mimeType' => isset($document['mimeType']) ? (string) $document['mimeType'] : 'application/pdf',
                ),
                'meta' => isset($decoded['meta']) && is_array($decoded['meta']) ? $decoded['meta'] : array(),
                'warnings' => isset($decoded['warnings']) && is_array($decoded['warnings']) ? $decoded['warnings'] : array(),
                'traceId' => $response_trace_id,
            );
        }

        /**
         * @param mixed $wp_error
         * @param string $trace_id
         * @param array<string,mixed> $transport_context
         * @return array<string,mixed>
         */
        private function classify_wp_error($wp_error, $trace_id, $transport_context) {
            $error_code = $this->read_wp_error_code($wp_error);
            $error_message = $this->read_wp_error_message($wp_error);
            $is_timeout = $this->is_timeout_error($error_code, $error_message);

            return $this->build_error_result(
                $is_timeout ? 'GENERATOR_TIMEOUT' : 'GENERATOR_HTTP_TRANSPORT_ERROR',
                $is_timeout
                    ? 'Generator request timed out.'
                    : ($error_message !== '' ? $error_message : 'Generator transport error.'),
                $this->build_error_details($transport_context, array(
                    'reason' => $is_timeout ? 'timeout' : 'wp_http_error',
                    'wpErrorCode' => $error_code,
                )),
                $is_timeout ? 504 : 502,
                true,
                $trace_id
            );
        }

        /**
         * @param int $status
         * @param mixed $decoded
         * @param string $trace_id
         * @param array<string,mixed> $transport_context
         * @return array<string,mixed>
         */
        private function classify_http_error($status, $decoded, $trace_id, $transport_context) {
            $upstream = $this->extract_upstream_error_payload($decoded);
            $response_trace_id = isset($upstream['traceId']) && is_string($upstream['traceId']) && trim($upstream['traceId']) !== ''
                ? trim((string) $upstream['traceId'])
                : $trace_id;
            $details = $this->build_error_details($transport_context, array(
                'reason' => 'http_error',
                'responseStatusField' => isset($upstream['status']) ? (string) $upstream['status'] : '',
                'upstreamErrorCode' => isset($upstream['errorCode']) ? (string) $upstream['errorCode'] : '',
                'upstreamTraceId' => isset($upstream['traceId']) ? (string) $upstream['traceId'] : '',
            ));

            if ($status === 401 || $status === 403) {
                return $this->build_error_result(
                    'GENERATOR_UPSTREAM_AUTH_FAILED',
                    isset($upstream['message']) && trim((string) $upstream['message']) !== ''
                        ? (string) $upstream['message']
                        : 'Generator rejected server-to-server credentials.',
                    $details,
                    $status,
                    false,
                    $response_trace_id
                );
            }

            if ($status === 404) {
                return $this->build_error_result(
                    'GENERATOR_ENDPOINT_NOT_FOUND',
                    'Generator endpoint returned 404 Not Found.',
                    $details,
                    404,
                    false,
                    $response_trace_id
                );
            }

            return $this->build_error_result(
                'GENERATOR_UPSTREAM_HTTP_ERROR',
                isset($upstream['message']) && trim((string) $upstream['message']) !== ''
                    ? (string) $upstream['message']
                    : ('Generator request failed with HTTP ' . $status . '.'),
                $details,
                $status > 0 ? $status : 502,
                $status >= 500 || $status === 408 || $status === 429,
                $response_trace_id
            );
        }

        /**
         * @param array<string,mixed> $result
         * @param array<string,mixed> $transport_context
         * @return array<string,mixed>
         */
        private function finalize_error($result, $transport_context) {
            $error = isset($result['error']) && is_array($result['error']) ? $result['error'] : array();
            $details = isset($error['details']) && is_array($error['details']) ? $error['details'] : array();

            $this->log_generator_event('warn', 'offer document generator request failed', array_merge(
                $transport_context,
                array(
                    'errorCode' => isset($error['code']) ? (string) $error['code'] : 'GENERATOR_REQUEST_FAILED',
                    'retryable' => !empty($result['retryable']),
                    'errorDetails' => $details,
                )
            ));

            return $result;
        }

        /**
         * @param string $code
         * @param string $message
         * @param array<string,mixed> $details
         * @param int $http_status
         * @param bool $retryable
         * @param string $trace_id
         * @return array<string,mixed>
         */
        private function build_error_result($code, $message, $details, $http_status, $retryable, $trace_id) {
            return array(
                'ok' => false,
                'retryable' => (bool) $retryable,
                'http_status' => (int) $http_status,
                'traceId' => (string) $trace_id,
                'error' => array(
                    'code' => (string) $code,
                    'message' => (string) $message,
                    'details' => $details,
                ),
            );
        }

        /**
         * @param array<string,mixed> $base
         * @param array<string,mixed> $extra
         * @return array<string,mixed>
         */
        private function build_error_details($base, $extra = array()) {
            $details = array(
                'requestMode' => isset($base['requestMode']) ? (string) $base['requestMode'] : self::REQUEST_MODE,
                'documentType' => isset($base['documentType']) ? (string) $base['documentType'] : self::DOCUMENT_TYPE,
                'outputFormat' => isset($base['outputFormat']) ? (string) $base['outputFormat'] : self::OUTPUT_FORMAT,
                'endpoint' => isset($base['endpoint']) ? (string) $base['endpoint'] : '',
                'endpointSource' => isset($base['endpointSource']) ? (string) $base['endpointSource'] : '',
                'endpointConfigType' => isset($base['endpointConfigType']) ? (string) $base['endpointConfigType'] : '',
                'keyPresent' => !empty($base['keyPresent']),
                'keySource' => isset($base['keySource']) ? (string) $base['keySource'] : '',
                'timeoutSeconds' => isset($base['timeoutSeconds']) ? (int) $base['timeoutSeconds'] : 0,
                'timeoutSource' => isset($base['timeoutSource']) ? (string) $base['timeoutSource'] : '',
                'dispatchMode' => isset($base['dispatchMode']) ? (string) $base['dispatchMode'] : '',
                'httpStatus' => isset($base['httpStatus']) ? (int) $base['httpStatus'] : 0,
                'responseParseResult' => isset($base['responseParseResult']) ? (string) $base['responseParseResult'] : '',
            );

            foreach ($extra as $key => $value) {
                if ($value === null || $value === '') {
                    continue;
                }
                $details[(string) $key] = $value;
            }

            return $details;
        }

        /**
         * @param mixed $decoded
         * @return array<string,mixed>
         */
        private function extract_upstream_error_payload($decoded) {
            if (!is_array($decoded)) {
                return array(
                    'message' => '',
                    'errorCode' => '',
                    'traceId' => '',
                    'status' => '',
                );
            }

            $error = isset($decoded['error']) && is_array($decoded['error']) ? $decoded['error'] : array();
            $details = isset($decoded['details']) && is_array($decoded['details']) ? $decoded['details'] : array();
            if (empty($details) && isset($error['details']) && is_array($error['details'])) {
                $details = $error['details'];
            }

            return array(
                'message' => isset($decoded['message']) && is_string($decoded['message']) && trim($decoded['message']) !== ''
                    ? trim((string) $decoded['message'])
                    : (isset($error['message']) && is_string($error['message']) ? trim((string) $error['message']) : ''),
                'errorCode' => isset($decoded['errorCode']) && is_scalar($decoded['errorCode'])
                    ? trim((string) $decoded['errorCode'])
                    : (isset($error['code']) && is_scalar($error['code']) ? trim((string) $error['code']) : ''),
                'traceId' => isset($decoded['traceId']) && is_scalar($decoded['traceId'])
                    ? trim((string) $decoded['traceId'])
                    : '',
                'status' => isset($decoded['status']) && is_scalar($decoded['status'])
                    ? trim((string) $decoded['status'])
                    : '',
                'details' => $details,
            );
        }

        /**
         * @param string $method
         * @param string $fallback
         * @param array<string,mixed> $default
         * @return array<string,mixed>
         */
        private function resolve_config_bundle($method, $fallback, $default) {
            if (is_object($this->config) && method_exists($this->config, $method)) {
                $resolved = $this->config->{$method}();
                if (is_array($resolved)) {
                    return array_merge($default, $resolved);
                }
            }

            if (is_object($this->config) && method_exists($this->config, $fallback)) {
                $default['value'] = $this->config->{$fallback}();
            }

            return $default;
        }

        /**
         * @param array<string,mixed> $context
         * @param mixed $offer_dto
         * @return string
         */
        private function resolve_trace_id($context, $offer_dto) {
            $trace_id = isset($context['trace_id']) ? (string) $context['trace_id'] : '';
            if ($trace_id === '' && is_array($offer_dto) && isset($offer_dto['traceId'])) {
                $trace_id = (string) $offer_dto['traceId'];
            }

            if (function_exists('topinstal_ensure_trace_id')) {
                return topinstal_ensure_trace_id($trace_id);
            }

            $trace_id = trim((string) $trace_id);
            return $trace_id !== '' ? $trace_id : uniqid('offer_doc_', true);
        }

        /**
         * @param mixed $decoded
         * @param string $fallback
         * @return string
         */
        private function resolve_response_trace_id($decoded, $fallback) {
            if (is_array($decoded) && isset($decoded['traceId']) && is_scalar($decoded['traceId'])) {
                $trace_id = trim((string) $decoded['traceId']);
                if ($trace_id !== '') {
                    return $trace_id;
                }
            }

            return $fallback;
        }

        /**
         * @param mixed $error
         * @return string
         */
        private function read_wp_error_code($error) {
            if (is_object($error) && method_exists($error, 'get_error_code')) {
                return trim((string) $error->get_error_code());
            }
            if (is_array($error) && isset($error['code'])) {
                return trim((string) $error['code']);
            }
            return '';
        }

        /**
         * @param mixed $error
         * @return string
         */
        private function read_wp_error_message($error) {
            if (is_object($error) && method_exists($error, 'get_error_message')) {
                return trim((string) $error->get_error_message());
            }
            if (is_array($error) && isset($error['message'])) {
                return trim((string) $error['message']);
            }
            return '';
        }

        /**
         * @param string $code
         * @param string $message
         * @return bool
         */
        private function is_timeout_error($code, $message) {
            $haystack = strtolower(trim($code . ' ' . $message));
            if ($haystack === '') {
                return false;
            }

            return strpos($haystack, 'timed out') !== false
                || strpos($haystack, 'timeout') !== false
                || strpos($haystack, 'operation timed out') !== false
                || strpos($haystack, 'curl error 28') !== false;
        }

        /**
         * @param string $level
         * @param string $message
         * @param array<string,mixed> $context
         * @return void
         */
        private function log_generator_event($level, $message, $context = array()) {
            if (!class_exists('TopInstal_Logger_Wp')) {
                return;
            }

            if ($level === 'warn') {
                TopInstal_Logger_Wp::warn($message, $context);
                return;
            }
            if ($level === 'error') {
                TopInstal_Logger_Wp::error($message, $context);
                return;
            }

            TopInstal_Logger_Wp::info($message, $context);
        }

        /**
         * @param array<string,mixed> $resolution
         * @return string
         */
        private function describe_resolution_source($resolution) {
            $source = isset($resolution['source']) ? trim((string) $resolution['source']) : '';
            $source_name = isset($resolution['sourceName']) ? trim((string) $resolution['sourceName']) : '';

            if ($source === '' || $source === 'missing') {
                return 'missing';
            }
            if ($source_name === '' || $source_name === 'default') {
                return $source;
            }

            return $source . ':' . $source_name;
        }

        /**
         * @param mixed $value
         * @return string
         */
        private function normalize_url_string($value) {
            if (!is_string($value)) {
                return '';
            }

            $trimmed = trim($value);
            if ($trimmed === '') {
                return '';
            }

            $normalized = preg_replace('/\s+/', '', $trimmed);
            return is_string($normalized) ? trim($normalized) : $trimmed;
        }

        /**
         * @param string $url
         * @return bool
         */
        private function is_valid_url($url) {
            $url = $this->normalize_url_string($url);
            if ($url === '') {
                return false;
            }

            if (function_exists('wp_http_validate_url')) {
                return wp_http_validate_url($url) !== false;
            }

            return filter_var($url, FILTER_VALIDATE_URL) !== false;
        }

        /**
         * @return string
         */
        private function get_generator_route() {
            if (is_object($this->config) && method_exists($this->config, 'get_generator_route')) {
                return (string) $this->config->get_generator_route();
            }

            return '/wp-json/topinstal/v1/offer-documents/generate';
        }

        /**
         * @param string $code
         * @param string $message
         * @return mixed
         */
        private function create_wp_error($code, $message) {
            if (class_exists('WP_Error')) {
                return new WP_Error($code, $message);
            }

            return array(
                'code' => $code,
                'message' => $message,
            );
        }

        /**
         * @param string $left
         * @param string $right
         * @return bool
         */
        private function urls_match($left, $right) {
            $left_parts = wp_parse_url((string) $left);
            $right_parts = wp_parse_url((string) $right);
            if (!is_array($left_parts) || !is_array($right_parts)) {
                return false;
            }

            $left_scheme = isset($left_parts['scheme']) ? strtolower((string) $left_parts['scheme']) : '';
            $right_scheme = isset($right_parts['scheme']) ? strtolower((string) $right_parts['scheme']) : '';
            $left_host = isset($left_parts['host']) ? strtolower((string) $left_parts['host']) : '';
            $right_host = isset($right_parts['host']) ? strtolower((string) $right_parts['host']) : '';
            $left_port = isset($left_parts['port']) ? (int) $left_parts['port'] : (($left_scheme === 'https') ? 443 : 80);
            $right_port = isset($right_parts['port']) ? (int) $right_parts['port'] : (($right_scheme === 'https') ? 443 : 80);
            $left_path = isset($left_parts['path']) ? rtrim((string) $left_parts['path'], '/') : '';
            $right_path = isset($right_parts['path']) ? rtrim((string) $right_parts['path'], '/') : '';

            return $left_scheme === $right_scheme
                && $left_host === $right_host
                && $left_port === $right_port
                && $left_path === $right_path;
        }
    }
}
