<?php
/**
 * Plugin Name: Eager RankMath REST Expose
 * Description: Exposes Rank Math's real SEO scores (rank_math_seo_score) via REST so SEO Advisor can prioritize pages without an AI audit (~$0, RankMath already computed the score).
 * Version: 1.1.0
 * Author: Eager to Be Healthy
 *
 * INSTALL (pick one):
 *   A) mu-plugin (auto-on):
 *        wp-content/mu-plugins/eager-rankmath-rest.php
 *   B) normal plugin:
 *        wp-content/plugins/eager-rankmath-rest/eager-rankmath-rest.php
 *        then Activate in WP Admin
 *
 * VERIFY from 5by5:
 *   curl -s "https://www.eagertobehealthy.com/wp-json/etbh-seo/v1/rankmath-scores?per_page=3" | head
 *   # or authenticated:
 *   python -c "import wp_client; print(wp_client.list_content_with_rankmath(3))"
 */

if (!defined('ABSPATH')) {
    exit;
}

/**
 * Register Rank Math meta on posts/pages for standard REST ?meta / field use.
 */
add_action('init', function () {
    $keys = [
        'rank_math_seo_score'     => 'integer',
        'rank_math_focus_keyword' => 'string',
        'rank_math_title'         => 'string',
        'rank_math_description'   => 'string',
    ];

    foreach (['post', 'page'] as $type) {
        foreach ($keys as $meta_key => $type_name) {
            register_post_meta($type, $meta_key, [
                'show_in_rest'  => true,
                'single'        => true,
                'type'          => $type_name,
                // Public read of scores is intentional for SEO Advisor handoff.
                // Change to a capability check if you prefer auth-only.
                'auth_callback' => '__return_true',
            ]);
        }
    }
}, 20);

/**
 * rankmath object on every post/page in wp/v2 REST.
 */
add_action('rest_api_init', function () {
    foreach (['post', 'page'] as $type) {
        register_rest_field($type, 'rankmath', [
            'get_callback' => function ($obj) {
                return etbh_rankmath_payload((int) $obj['id']);
            },
            'schema' => [
                'description' => 'Rank Math SEO fields (real plugin score)',
                'type'        => 'object',
            ],
        ]);
    }

    /**
     * Bulk list — what SEO Advisor prefers (cheap, one call).
     * GET /wp-json/etbh-seo/v1/rankmath-scores?per_page=100&page=1
     *
     * Public by default so 5by5 can pull scores without admin RankMath caps.
     * Editors hit 403 on /rankmath/v1/links/posts; this bypasses that gate
     * by reading post meta RankMath already stored.
     */
    register_rest_route('etbh-seo/v1', '/rankmath-scores', [
        'methods'             => 'GET',
        'permission_callback' => '__return_true',
        'args'                => [
            'per_page' => [
                'type'    => 'integer',
                'default' => 100,
                'minimum' => 1,
                'maximum' => 100,
            ],
            'page' => [
                'type'    => 'integer',
                'default' => 1,
                'minimum' => 1,
            ],
            'post_type' => [
                'type'    => 'string',
                'default' => 'post,page',
            ],
            'max_score' => [
                'description' => 'Only include scores strictly below this (e.g. 80)',
                'type'        => 'integer',
                'required'    => false,
            ],
        ],
        'callback' => function (WP_REST_Request $req) {
            $types = array_filter(array_map('trim', explode(',', (string) $req['post_type'])));
            if (!$types) {
                $types = ['post', 'page'];
            }

            $q = new WP_Query([
                'post_type'      => $types,
                'post_status'    => 'publish',
                'posts_per_page' => (int) $req['per_page'],
                'paged'          => (int) $req['page'],
                'orderby'        => 'modified',
                'order'          => 'DESC',
                'no_found_rows'  => false,
            ]);

            $max_score = $req->get_param('max_score');
            $items     = [];

            foreach ($q->posts as $post) {
                $payload = etbh_rankmath_payload((int) $post->ID);
                $score   = $payload['seo_score'];

                if ($max_score !== null && $score !== null && (int) $score >= (int) $max_score) {
                    continue;
                }

                $items[] = [
                    'id'    => (int) $post->ID,
                    'title' => get_the_title($post),
                    'url'   => get_permalink($post),
                    'type'  => $post->post_type,
                    'slug'  => $post->post_name,
                    'rankmath' => $payload,
                    // flat fields for simple clients
                    'seo_score'     => $score,
                    'focus_keyword' => $payload['focus_keyword'],
                ];
            }

            // Sort improvable-first: lowest score first, nulls last
            usort($items, function ($a, $b) {
                $sa = $a['seo_score'];
                $sb = $b['seo_score'];
                if ($sa === null && $sb === null) {
                    return 0;
                }
                if ($sa === null) {
                    return 1;
                }
                if ($sb === null) {
                    return -1;
                }
                return $sa <=> $sb;
            });

            return rest_ensure_response([
                'source'       => 'rank_math_seo_score meta (plugin-computed, not AI)',
                'total'        => (int) $q->found_posts,
                'total_pages'  => (int) $q->max_num_pages,
                'page'         => (int) $req['page'],
                'per_page'     => (int) $req['per_page'],
                'items'        => $items,
            ]);
        },
    ]);
});

/**
 * @return array{seo_score:?int,focus_keyword:string,meta_title:string,meta_description:string,score_source:string}
 */
function etbh_rankmath_payload(int $post_id): array {
    $score = get_post_meta($post_id, 'rank_math_seo_score', true);
    if ($score === '' || $score === null || $score === false) {
        $score = null;
    } else {
        $score = (int) $score;
    }

    return [
        'seo_score'        => $score,
        'focus_keyword'    => (string) get_post_meta($post_id, 'rank_math_focus_keyword', true),
        'meta_title'       => (string) get_post_meta($post_id, 'rank_math_title', true),
        'meta_description' => (string) get_post_meta($post_id, 'rank_math_description', true),
        'score_source'     => 'rank_math_seo_score',
    ];
}
