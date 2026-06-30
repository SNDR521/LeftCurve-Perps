/**
 * Base64url helpers for encoding position_key values in URL path segments.
 *
 * position_key strings (e.g. "1:HYPE/USDC:rt:0xabc") contain "/" and ":"
 * which are not URL-path-safe.  Standard base64 adds "+" and "/" which are
 * also not safe in paths.  Base64url (RFC 4648 §5) replaces those characters
 * and strips "=" padding so the result is safe in any URL segment.
 *
 * position_key values are always ASCII so btoa/atob are safe to use here.
 */

export function encodePositionKey(key) {
  return btoa(key).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '')
}

export function decodePositionKey(encoded) {
  // Re-add stripped "=" padding: length must be a multiple of 4
  const pad = (4 - (encoded.length % 4)) % 4
  const padded = encoded + '='.repeat(pad)
  return atob(padded.replace(/-/g, '+').replace(/_/g, '/'))
}
