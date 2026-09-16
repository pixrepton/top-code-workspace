<?php

if (!defined('ABSPATH')) {
    exit;
}

if (!class_exists('TopInstal_MailIngressWorkflowConfig')) {
    class TopInstal_MailIngressWorkflowConfig {
        const GENERATOR_ROUTE = '/wp-json/topinstal/v1/offer-documents/generate';
        const GENERATOR_DEFAULT_ENDPOINT = '';

        public function is_enabled() {
            return $this->get_bool('topinstal_mail_ingress_workflow_enabled', 'TOPINSTAL_MAIL_INGRESS_WORKFLOW_ENABLED', true);
        }

        public function get_generator_endpoint() {
            $resolved = $this->resolve_generator_endpoint();
            return isset($resolved['value']) ? (string) $resolved['value'] : '';
        }

        public function get_generator_key() {
            $resolved = $this->resolve_generator_key();
            return isset($resolved['value']) ? (string) $resolved['value'] : '';
        }

        public function get_generator_timeout() {
            $resolved = $this->resolve_generator_timeout();
            return isset($resolved['value']) ? (int) $resolved['value'] : 120;
        }

        /**
         * Resolve the generator endpoint with explicit source tracking.
         *
         * Fallback order:
         * 1. TOPINSTAL_MAIL_INGRESS_GENERATOR_ENDPOINT / option
         * 2. TOPINSTAL_AGENT_OFFER_DOCUMENTS_ENDPOINT / option
         * 3. TOPINSTAL_MAIL_INGRESS_GENERATOR_BASE_URL / option + canonical route
         * 4. fail closed (missing endpoint)
         *
         * @return array<string,mixed>
         */
        public function resolve_generator_endpoint() {
            $candidates = array(
                array(
                    'option_name' => 'topinstal_mail_ingress_generator_endpoint',
                    'const_name' => 'TOPINSTAL_MAIL_INGRESS_GENERATOR_ENDPOINT',
                    'config_type' => 'endpoint',
                ),
                array(
                    'option_name' => 'topinstal_agent_offer_documents_endpoint',
                    'const_name' => 'TOPINSTAL_AGENT_OFFER_DOCUMENTS_ENDPOINT',
                    'config_type' => 'endpoint',
                ),
                array(
                    'option_name' => 'topinstal_mail_ingress_generator_base_url',
                    'const_name' => 'TOPINSTAL_MAIL_INGRESS_GENERATOR_BASE_URL',
                    'config_type' => 'base_url',
                ),
            );

            foreach ($candidates as $candidate) {
                $bundle = $this->get_string_bundle(
                    isset($candidate['option_name']) ? (string) $candidate['option_name'] : '',
                    isset($candidate['const_name']) ? (string) $candidate['const_name'] : '',
                    ''
                );
                $raw_value = $this->normalize_url_string(isset($bundle['value']) ? $bundle['value'] : '');
                if ($raw_value === '') {
                    continue;
                }

                $resolved_value = isset($candidate['config_type']) && $candidate['config_type'] === 'base_url'
                    ? $this->build_generator_endpoint_from_base_url($raw_value)
                    : $raw_value;
                if ($resolved_value === '') {
                    continue;
                }

                $bundle['value'] = $resolved_value;
                $bundle['rawValue'] = $raw_value;
                $bundle['configType'] = isset($candidate['config_type']) ? (string) $candidate['config_type'] : 'endpoint';
                $bundle['route'] = self::GENERATOR_ROUTE;
                return $bundle;
            }

            return array(
                'value' => '',
                'rawValue' => '',
                'configType' => 'missing',
                'route' => self::GENERATOR_ROUTE,
                'source' => 'missing',
                'sourceName' => '',
            );
        }

        /**
         * Resolve the generator key with explicit source tracking.
         *
         * Fallback order:
         * 1. TOPINSTAL_MAIL_INGRESS_GENERATOR_KEY / option
         * 2. TOPINSTAL_AGENT_OFFER_DOCUMENTS_KEY / option
         *
         * @return array<string,mixed>
         */
        public function resolve_generator_key() {
            $candidates = array(
                array(
                    'option_name' => 'topinstal_mail_ingress_generator_key',
                    'const_name' => 'TOPINSTAL_MAIL_INGRESS_GENERATOR_KEY',
                ),
                array(
                    'option_name' => 'topinstal_agent_offer_documents_key',
                    'const_name' => 'TOPINSTAL_AGENT_OFFER_DOCUMENTS_KEY',
                ),
            );

            foreach ($candidates as $candidate) {
                $bundle = $this->get_secret_bundle(
                    isset($candidate['option_name']) ? (string) $candidate['option_name'] : '',
                    isset($candidate['const_name']) ? (string) $candidate['const_name'] : '',
                    ''
                );
                $value = $this->normalize_config_string(isset($bundle['value']) ? $bundle['value'] : '');
                if ($value === '') {
                    continue;
                }

                $bundle['value'] = $value;
                $bundle['present'] = true;
                return $bundle;
            }

            return array(
                'value' => '',
                'present' => false,
                'source' => 'missing',
                'sourceName' => '',
            );
        }

        /**
         * @return array<string,mixed>
         */
        public function resolve_generator_timeout() {
            return $this->get_int_bundle(
                'topinstal_mail_ingress_generator_timeout',
                'TOPINSTAL_MAIL_INGRESS_GENERATOR_TIMEOUT',
                120,
                5,
                300
            );
        }

        /**
         * @return array<string,mixed>
         */
        public function get_generator_debug_summary() {
            $endpoint = $this->resolve_generator_endpoint();
            $key = $this->resolve_generator_key();
            $timeout = $this->resolve_generator_timeout();

            return array(
                'resolvedEndpoint' => isset($endpoint['value']) ? (string) $endpoint['value'] : '',
                'endpointConfigType' => isset($endpoint['configType']) ? (string) $endpoint['configType'] : 'missing',
                'endpointSource' => $this->format_bundle_source($endpoint),
                'keyPresent' => !empty($key['present']),
                'keySource' => $this->format_bundle_source($key),
                'timeoutSeconds' => isset($timeout['value']) ? (int) $timeout['value'] : 120,
                'timeoutSource' => $this->format_bundle_source($timeout),
            );
        }

        /**
         * @return string
         */
        public function get_generator_route() {
            return self::GENERATOR_ROUTE;
        }

        public function get_cieplo_fetch_timeout() {
            return $this->get_int('topinstal_mail_ingress_cieplo_fetch_timeout', 'TOPINSTAL_MAIL_INGRESS_CIEPLO_FETCH_TIMEOUT', 35, 5, 180);
        }

        public function get_cieplo_user_agent() {
            return $this->get_string('topinstal_mail_ingress_cieplo_user_agent', 'TOPINSTAL_MAIL_INGRESS_CIEPLO_USER_AGENT', 'TOPINSTAL-MailIngressWorkflow/1.0');
        }

        public function get_review_recipient() {
            $email = $this->get_string('topinstal_mail_ingress_review_recipient', 'TOPINSTAL_MAIL_INGRESS_REVIEW_RECIPIENT', '');
            if ($email !== '') {
                return sanitize_email($email);
            }

            return sanitize_email($this->get_string('topinstal_agent_review_email', 'AGENT_REVIEW_EMAIL', ''));
        }

        public function get_review_subject_prefix() {
            return $this->get_string('topinstal_mail_ingress_review_subject_prefix', 'TOPINSTAL_MAIL_INGRESS_REVIEW_SUBJECT_PREFIX', '[TOP-INSTAL][MailIngress Review]');
        }

        public function get_defaults_policy() {
            return array(
                'schemaVersion' => '1.0',
                'building' => array(
                    'heated_area' => 150.0,
                    'include_hot_water' => true,
                    'hot_water_persons' => 3,
                    'hot_water_usage' => 'shower_bath',
                ),
                'preferences' => array(
                    'heating' => array(
                        'emitterType' => 'radiators',
                        'sourceType' => 'air_to_water_hp',
                    ),
                    'dhw' => array(
                        'enabled' => true,
                        'persons' => 3,
                        'usageProfile' => 'shower_bath',
                    ),
                    'hasBuffer' => false,
                ),
                'ozc' => array(
                    'designHeatLoss_kW' => 9.0,
                    'recommendedPower_kW' => 9.0,
                    'heatedArea_m2' => 150.0,
                ),
            );
        }

        public function get_string($option_name, $const_name, $default = '') {
            $bundle = $this->get_string_bundle($option_name, $const_name, $default);
            return isset($bundle['value']) ? (string) $bundle['value'] : (string) $default;
        }

        public function get_bool($option_name, $const_name, $default = false) {
            $raw = $this->get_string($option_name, $const_name, $default ? '1' : '0');
            return $this->coerce_bool_string($raw, $default);
        }

        /**
         * @param mixed $value
         * @param bool $default
         * @return bool
         */
        private function coerce_bool_string($value, $default = false) {
            if ($value === null || $value === '') {
                return $default;
            }
            if (is_bool($value)) {
                return $value;
            }
            if (is_numeric($value)) {
                return ((int) $value) === 1;
            }
            if (is_string($value)) {
                $normalized = strtolower(trim($value));
                if (in_array($normalized, array('1', 'true', 'yes', 'on'), true)) {
                    return true;
                }
                if (in_array($normalized, array('0', 'false', 'no', 'off'), true)) {
                    return false;
                }
            }
            return $default;
        }

        public function get_int($option_name, $const_name, $default, $min, $max) {
            $bundle = $this->get_int_bundle($option_name, $const_name, $default, $min, $max);
            return isset($bundle['value']) ? (int) $bundle['value'] : (int) $default;
        }

        /**
         * @param string $option_name
         * @param string $const_name
         * @param mixed $default
         * @return array<string,mixed>
         */
        private function get_string_bundle($option_name, $const_name, $default = '') {
            if ($const_name !== '' && defined($const_name)) {
                $value = constant($const_name);
                if (is_string($value) && trim($value) !== '') {
                    return array(
                        'value' => trim($value),
                        'source' => 'constant',
                        'sourceName' => $const_name,
                    );
                }
            }

            if ($const_name !== '') {
                $env = getenv($const_name);
                if (is_string($env) && trim($env) !== '') {
                    return array(
                        'value' => trim($env),
                        'source' => 'env',
                        'sourceName' => $const_name,
                    );
                }
            }

            if ($option_name !== '' && function_exists('get_option')) {
                $option = get_option($option_name, '');
                if (is_string($option) && trim($option) !== '') {
                    return array(
                        'value' => trim($option),
                        'source' => 'option',
                        'sourceName' => $option_name,
                    );
                }
            }

            return array(
                'value' => (string) $default,
                'source' => 'default',
                'sourceName' => 'default',
            );
        }

        /**
         * @param string $option_name
         * @param string $const_name
         * @param int $default
         * @param int $min
         * @param int $max
         * @return array<string,mixed>
         */
        private function get_int_bundle($option_name, $const_name, $default, $min, $max) {
            $bundle = $this->get_string_bundle($option_name, $const_name, (string) $default);
            $raw = isset($bundle['value']) ? (string) $bundle['value'] : (string) $default;
            $value = is_numeric($raw) ? (int) $raw : (int) $default;
            if ($value < $min) {
                $value = $min;
            }
            if ($value > $max) {
                $value = $max;
            }
            $bundle['value'] = $value;
            return $bundle;
        }

        private function get_secret($option_name, $const_name, $default = '') {
            $bundle = $this->get_secret_bundle($option_name, $const_name, $default);
            return isset($bundle['value']) ? (string) $bundle['value'] : (string) $default;
        }

        /**
         * @param string $option_name
         * @param string $const_name
         * @param mixed $default
         * @return array<string,mixed>
         */
        private function get_secret_bundle($option_name, $const_name, $default = '') {
            if (class_exists('TopInstal_Agent_SecretStore')) {
                $bundle = TopInstal_Agent_SecretStore::get_bundle($option_name, $const_name, '');
                if (isset($bundle['active']) && is_string($bundle['active']) && trim($bundle['active']) !== '') {
                    return array(
                        'value' => trim((string) $bundle['active']),
                        'source' => isset($bundle['source']) ? (string) $bundle['source'] : 'secret_store',
                        'sourceName' => $this->source_name_for_bundle(
                            isset($bundle['source']) ? (string) $bundle['source'] : 'secret_store',
                            $option_name,
                            $const_name
                        ),
                    );
                }
            }

            return $this->get_string_bundle($option_name, $const_name, $default);
        }

        /**
         * @param mixed $value
         * @return string
         */
        private function normalize_config_string($value) {
            return is_string($value) ? trim($value) : '';
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
         * @param string $base_url
         * @return string
         */
        private function build_generator_endpoint_from_base_url($base_url) {
            $base_url = $this->normalize_url_string($base_url);
            if ($base_url === '') {
                return '';
            }

            if (function_exists('untrailingslashit')) {
                return untrailingslashit($base_url) . self::GENERATOR_ROUTE;
            }

            return rtrim($base_url, '/') . self::GENERATOR_ROUTE;
        }

        /**
         * @param array<string,mixed> $bundle
         * @return string
         */
        private function format_bundle_source($bundle) {
            $source = isset($bundle['source']) ? trim((string) $bundle['source']) : '';
            $source_name = isset($bundle['sourceName']) ? trim((string) $bundle['sourceName']) : '';

            if ($source === '' || $source === 'missing') {
                return 'missing';
            }
            if ($source_name === '' || $source_name === 'default') {
                return $source;
            }

            return $source . ':' . $source_name;
        }

        /**
         * @param string $source
         * @param string $option_name
         * @param string $const_name
         * @return string
         */
        private function source_name_for_bundle($source, $option_name, $const_name) {
            if ($source === 'constant' || $source === 'env') {
                return $const_name;
            }
            if ($source === 'option') {
                return $option_name;
            }
            return $source;
        }
    }
}
