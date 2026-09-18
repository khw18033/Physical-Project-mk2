export type OriginKind = 'physical' | 'simulation' | 'replay';

export const ORIGIN_LABEL: Record<OriginKind, string> = {
  physical: t('pr.1'),
  simulation: t('pr.2'),
  replay: t('pr.3'),
};
import { t } from '../i18n/dict.ts';
