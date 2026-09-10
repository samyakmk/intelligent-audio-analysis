import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useAudioPlayer, useAudioPlayerStatus } from 'expo-audio';
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View, type GestureResponderEvent } from 'react-native';

import { Button } from '@/components/ui';
import { api } from '@/lib/api';
import { remainingEvidencePlaybackMs } from '@/lib/evidence';
import { formatDuration } from '@/lib/format';
import { colors, font, radius, spacing } from '@/theme';

const configuredRefreshSeconds = Number(process.env.EXPO_PUBLIC_MEDIA_GRANT_REFRESH_SECONDS ?? '45');
const grantRefreshMs = Math.max(5, Number.isFinite(configuredRefreshSeconds) ? configuredRefreshSeconds : 45) * 1000;

export interface RecordingAudioPlayerHandle {
  seekToMs(ms: number, autoplay?: boolean): void;
  playRangeMs(startMs: number, endMs: number): void;
}

export function LocalAudioPlayer({ uri }: { uri: string }) {
  const player = useAudioPlayer(uri, { updateInterval: 250 });
  const status = useAudioPlayerStatus(player);
  const [trackWidth, setTrackWidth] = useState(0);
  const progress = status.duration > 0
    ? Math.min(100, Math.max(0, (status.currentTime / status.duration) * 100))
    : 0;

  const seekFromPress = (event: GestureResponderEvent) => {
    if (!status.duration || !trackWidth) return;
    void player.seekTo((event.nativeEvent.locationX / trackWidth) * status.duration);
  };

  return (
    <View style={styles.previewRoot}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={status.playing ? 'Pause new recording' : 'Play new recording'}
        onPress={() => status.playing ? player.pause() : player.play()}
        style={({ pressed }) => [styles.previewPlayButton, pressed && styles.pressed]}
      >
        <MaterialCommunityIcons name={status.playing ? 'pause' : 'play'} size={22} color={colors.white} />
      </Pressable>
      <View style={styles.playerMain}>
        <View style={styles.playerTop}>
          <Text style={styles.previewLabel}>{status.playing ? 'Playing your recording' : 'Listen before you continue'}</Text>
          <Text style={styles.previewTime}>{formatDuration(status.currentTime * 1000)} / {formatDuration(status.duration * 1000)}</Text>
        </View>
        <Pressable
          accessibilityRole="adjustable"
          accessibilityLabel="New recording playback position"
          accessibilityValue={{ min: 0, max: Math.round(status.duration), now: Math.round(status.currentTime) }}
          onLayout={(event) => setTrackWidth(event.nativeEvent.layout.width)}
          onPress={seekFromPress}
          style={styles.previewTrack}
        >
          <View style={[styles.previewFill, { width: `${progress}%` }]} />
        </Pressable>
      </View>
    </View>
  );
}

export const RecordingAudioPlayer = forwardRef<
  RecordingAudioPlayerHandle,
  { recordingId: string }
>(function RecordingAudioPlayer({ recordingId }, ref) {
  const [url, setUrl] = useState<string>();
  const [grantExpiresAt, setGrantExpiresAt] = useState(0);
  const [error, setError] = useState<Error>();
  const [loading, setLoading] = useState(true);
  const [trackWidth, setTrackWidth] = useState(0);
  const player = useAudioPlayer(url ?? null, { updateInterval: 250 });
  const status = useAudioPlayerStatus(player);
  const resumeRef = useRef<{ position: number; autoplay: boolean; stopAt?: number } | undefined>(undefined);
  const stopAtRef = useRef<number | undefined>(undefined);
  const [rangeEnd, setRangeEnd] = useState<number>();

  const renewGrant = useCallback(async ({
    position = player.currentTime,
    autoplay = false,
    showLoading = false,
    stopAt = stopAtRef.current,
  }: {
    position?: number;
    autoplay?: boolean;
    showLoading?: boolean;
    stopAt?: number;
  } = {}) => {
    if (showLoading) setLoading(true);
    try {
      const grant = await api.mediaGrant(recordingId, 'playback');
      resumeRef.current = { position, autoplay, stopAt };
      setUrl(grant.url);
      setGrantExpiresAt(Date.parse(grant.expires_at));
      setError(undefined);
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('Playback is unavailable'));
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [player, recordingId]);

  useEffect(() => {
    let active = true;
    api.mediaGrant(recordingId, 'playback')
      .then((grant) => {
        if (!active) return;
        setUrl(grant.url);
        setGrantExpiresAt(Date.parse(grant.expires_at));
        setError(undefined);
      })
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught : new Error('Playback is unavailable'));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [recordingId]);

  useEffect(() => {
    const resume = resumeRef.current;
    if (!url || !resume) return;
    resumeRef.current = undefined;
    stopAtRef.current = resume.stopAt;
    void player.seekTo(resume.position).then(() => {
      if (resume.autoplay) player.play();
    });
  }, [player, url]);

  useEffect(() => {
    if (!status.playing || !grantExpiresAt) return;
    const delay = Math.max(0, Math.min(grantRefreshMs, grantExpiresAt - Date.now() - 5_000));
    const timer = setTimeout(() => {
      void renewGrant({ position: player.currentTime, autoplay: true, stopAt: stopAtRef.current });
    }, delay);
    return () => clearTimeout(timer);
  }, [grantExpiresAt, player, renewGrant, status.playing]);

  useEffect(() => {
    const stopAt = stopAtRef.current;
    if (!status.playing || stopAt === undefined) return;
    const stop = () => {
      player.pause();
      stopAtRef.current = undefined;
      void player.seekTo(stopAt);
    };
    const remainingMs = remainingEvidencePlaybackMs(status.currentTime, stopAt);
    if (remainingMs === 0) {
      stop();
      return;
    }
    const timer = setTimeout(stop, remainingMs);
    return () => clearTimeout(timer);
  }, [player, status.currentTime, status.playing]);

  const seekTo = useCallback((position: number, autoplay = false, stopAt?: number) => {
    stopAtRef.current = stopAt;
    setRangeEnd(stopAt);
    if (!url) {
      resumeRef.current = { position, autoplay, stopAt };
      return;
    }
    if (grantExpiresAt <= Date.now() + 5_000) {
      void renewGrant({ position, autoplay, stopAt });
      return;
    }
    void player.seekTo(position).then(() => {
      if (autoplay) player.play();
    });
  }, [grantExpiresAt, player, renewGrant, url]);

  useImperativeHandle(ref, () => ({
    seekToMs(ms: number, autoplay = true) {
      seekTo(Math.max(0, ms) / 1000, autoplay);
    },
    playRangeMs(startMs: number, endMs: number) {
      const start = Math.max(0, startMs) / 1_000;
      const end = Math.max(0, endMs) / 1_000;
      seekTo(start, true, end > start ? end : undefined);
    },
  }), [seekTo]);

  const seekFromPress = (event: GestureResponderEvent) => {
    if (!status.duration) return;
    if (trackWidth) seekTo((event.nativeEvent.locationX / trackWidth) * status.duration);
  };
  const progress = status.duration > 0 ? Math.min(100, Math.max(0, (status.currentTime / status.duration) * 100)) : 0;

  return (
    <View style={styles.root}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={status.playing ? 'Pause recording' : 'Play recording'}
        disabled={!url || loading}
        onPress={() => {
          if (status.playing) {
            player.pause();
          } else if (grantExpiresAt <= Date.now() + 5_000) {
            const continuingRange = rangeEnd !== undefined && player.currentTime < rangeEnd;
            if (!continuingRange) {
              setRangeEnd(undefined);
              stopAtRef.current = undefined;
            }
            void renewGrant({ autoplay: true, stopAt: continuingRange ? rangeEnd : undefined });
          } else {
            if (rangeEnd !== undefined && player.currentTime >= rangeEnd) {
              setRangeEnd(undefined);
              stopAtRef.current = undefined;
            } else if (rangeEnd !== undefined) {
              stopAtRef.current = rangeEnd;
            }
            player.play();
          }
        }}
        style={({ pressed }) => [styles.playButton, pressed && styles.pressed]}
      >
        {loading ? (
          <ActivityIndicator size="small" color={colors.white} />
        ) : (
          <MaterialCommunityIcons name={status.playing ? 'pause' : 'play'} size={26} color={colors.white} />
        )}
      </Pressable>
      <View style={styles.playerMain}>
        <View style={styles.playerTop}>
          <Text style={styles.playerLabel}>{error ? error.message : rangeEnd !== undefined ? status.playing ? 'Playing cited evidence' : 'Cited evidence' : status.playing ? 'Playing source audio' : 'Source audio'}</Text>
          <Text style={styles.time}>{formatDuration(status.currentTime * 1000)} / {formatDuration(status.duration * 1000)}</Text>
        </View>
        <Pressable
          accessibilityRole="adjustable"
          accessibilityLabel="Playback position"
          accessibilityValue={{ min: 0, max: Math.round(status.duration), now: Math.round(status.currentTime) }}
          accessibilityActions={[
            { name: 'decrement', label: 'Back 15 seconds' },
            { name: 'increment', label: 'Forward 15 seconds' },
          ]}
          onAccessibilityAction={(event) => {
            if (event.nativeEvent.actionName === 'decrement') seekTo(Math.max(0, status.currentTime - 15));
            if (event.nativeEvent.actionName === 'increment') seekTo(Math.min(status.duration, status.currentTime + 15));
          }}
          onLayout={(event) => setTrackWidth(event.nativeEvent.layout.width)}
          onPress={seekFromPress}
          style={styles.track}
        >
          <View style={[styles.fill, { width: `${progress}%` }]} />
        </Pressable>
      </View>
      <View style={styles.seekButtons}>
        <Pressable accessibilityRole="button" accessibilityLabel="Back 15 seconds" onPress={() => seekTo(Math.max(0, status.currentTime - 15))}>
          <MaterialCommunityIcons name="rewind-15" size={22} color={colors.inkMuted} />
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Forward 15 seconds" onPress={() => seekTo(Math.min(status.duration, status.currentTime + 15))}>
          <MaterialCommunityIcons name="fast-forward-15" size={22} color={colors.inkMuted} />
        </Pressable>
      </View>
      {error ? <Button size="sm" variant="secondary" onPress={() => renewGrant({ showLoading: true })}>Retry</Button> : null}
    </View>
  );
});

const styles = StyleSheet.create({
  root: { minHeight: 80, flexDirection: 'row', alignItems: 'center', gap: spacing.lg, padding: spacing.lg, borderRadius: radius.lg, backgroundColor: colors.pine },
  playButton: { width: 48, height: 48, borderRadius: 24, backgroundColor: colors.coral, alignItems: 'center', justifyContent: 'center' },
  pressed: { opacity: 0.75 },
  playerMain: { flex: 1, minWidth: 100, gap: 9 },
  playerTop: { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.md },
  playerLabel: { flex: 1, color: colors.white, fontFamily: font.medium, fontSize: 12 },
  time: { color: '#C8DDD6', fontFamily: font.mono, fontSize: 10 },
  track: { height: 8, borderRadius: 4, backgroundColor: '#315651', overflow: 'hidden' },
  fill: { height: 8, borderRadius: 4, backgroundColor: colors.coral },
  seekButtons: { flexDirection: 'row', gap: spacing.md },
  previewRoot: { minHeight: 66, flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.md, borderRadius: radius.md, backgroundColor: colors.pine },
  previewPlayButton: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.coral, alignItems: 'center', justifyContent: 'center' },
  previewLabel: { flex: 1, color: colors.white, fontFamily: font.medium, fontSize: 11 },
  previewTime: { color: '#C8DDD6', fontFamily: font.mono, fontSize: 9 },
  previewTrack: { height: 7, borderRadius: 4, backgroundColor: '#315651', overflow: 'hidden' },
  previewFill: { height: 7, borderRadius: 4, backgroundColor: colors.coral },
});
