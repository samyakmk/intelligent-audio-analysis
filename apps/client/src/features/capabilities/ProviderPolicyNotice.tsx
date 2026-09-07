import { Notice } from '@/components/ui';
import { isSyntheticApprovedOnly } from '@/features/capabilities/capabilities';
import { useCapabilities } from '@/providers/CapabilitiesProvider';

export function ProviderPolicyNotice() {
  const { capabilities, source, loading, error } = useCapabilities();
  if (!isSyntheticApprovedOnly(capabilities)) return null;

  const remote = capabilities.provider_mode === 'gemini' && capabilities.remote_processing;
  return (
    <Notice tone="warning" title="Synthetic or explicitly approved audio only">
      {remote
        ? 'Gemini processing is active under the synthetic-approved-only policy. Do not submit private, production, or otherwise unapproved recordings.'
        : 'The active policy permits only synthetic or explicitly approved audio. Remote Gemini processing is not currently enabled.'}
      {loading
        ? ' Provider capabilities are being verified; Deep remains safely disabled while this check completes.'
        : source === 'fixture-fallback' || error
          ? ' The client could not verify remote capabilities, so Deep remains safely disabled.'
        : ''}
    </Notice>
  );
}
