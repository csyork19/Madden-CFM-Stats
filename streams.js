/* League streams: one entry per game, keyed by week then "AWAY@HOME" (team abbreviations as shown on the scoreboard).
 *
 *   platform  'twitch' or 'youtube'
 *   url       the channel, live or video link. Leave '' until you have it; the card shows a placeholder.
 *   by        optional: who is streaming
 *
 * Twitch:  https://www.twitch.tv/<channel>   or   https://www.twitch.tv/videos/<id>
 * YouTube: https://www.youtube.com/watch?v=<id>,  https://youtu.be/<id>,  https://www.youtube.com/live/<id>
 *
 * The entries below are examples with no link yet. Replace them with your own.
 */
window.LEAGUE_STREAMS = {
  games: {
    "1": {
      "CHI@CAR": { platform: 'twitch', url: '', by: 'koryea' }
    },
    "2": {
      "CAR@ATL": { platform: 'twitch', url: '', by: 'koryea' },
      "WAS@DAL": { platform: 'youtube', url: '' }
    }
  }
};
