import { previewInstant } from './candidatePreviewInstant.ts';
export const EXPERIMENT_OPTIONS = [
    { kind: 'osc-test', label: '测试1', description: '震荡策略 · 7%止损；止损优先，同根不再建仓' },
    { kind: 'osc-test2', label: '测试2', description: '7%止损 · 建仓时锁定HHV10目标' },
    { kind: 'osc-test3', label: '测试3', description: '7%止损 · 前两根MA10严格上升才允许建仓' },
    { kind: 'osc-test4', label: '测试4', description: '12%止损 · 触及上轨记录收盘价，后续确认清仓' },
] as const;
export type ExperimentKind = typeof EXPERIMENT_OPTIONS[number]['kind'];
export interface ExperimentRequest {
    product: string;
    frequency: string;
    kind: ExperimentKind;
    as_of: string;
    snapshot_token?: string;
    reference_part?: 'panel' | 'history';
    reference_mode?: 'ordinary' | 'theoretical';
    segment_id?: string;
    history_before?: string;
    history_limit?: number;
    chart_limit?: number;
    from?: string;
    through?: string;
    all_history?: boolean;
}
export interface ExperimentBar {
    bar_end: string;
    trading_day: string;
    physical_contract: string;
    segment_id: string;
    open: string;
    high: string;
    low: string;
    close: string;
    channel_high: string | null;
    channel_low: string | null;
}
export interface ExperimentMarker {
    marker_id: string;
    bar_end: string;
    physical_contract: string;
    segment_id: string;
    action: 'BUILD' | 'CLEAR';
    reference_price: string;
    score: number;
    break_label: string | null;
    stop_loss: boolean;
    confirm_exit: boolean;
}
export interface ExperimentSegment {
    segment_id: string;
    physical_contract: string;
    status: 'CURRENT' | 'ROLLOVER_INTERRUPTED' | 'DATA_CONFLICT';
    readiness?: {
        status: 'READY' | 'WARMUP' | 'DATA_INSUFFICIENT';
        reason_code: string | null;
    };
    latest_state?: {
        holding: boolean;
        entry_reference_price: string | null;
        stop_reference_price: string | null;
        locked_target: string | null;
        confirm_reference: string | null;
    };
    statistics_window?: {
        since: string;
        through: string;
    };
    ordinary: Record<string, unknown> | null;
    theoretical: Record<string, unknown> | null;
}
export interface ExperimentDetail extends ExperimentRequest {
    schema_version: 'newow_experiment_detail_v2';
    meta: {
      identity: {product:string;frequency:string;kind:ExperimentKind;strategy:ExperimentKind;series_kind:'actual_dominant';as_of:string;formula_version:string;profile_id:string;input_policy_version:string};
      as_of:string; read_at:string; input_content_sha256:string; data_revision_identity:string|null;
      snapshot_token:string; result_hash:string; completed_only:true; executable:false; auto_order:false;
      last_completed_bar_end:string|null; last_trading_day:string|null;
    };
    input_snapshot_hash:string;
    profile_id:string;
    input_policy_version:string;
    window?: {
        since: string;
        through: string;
    };
    formula_version: string;
    page_parity: true;
    executable: false;
    readiness: {
        status: 'READY' | 'WARMUP' | 'DATA_INSUFFICIENT';
        reason_code: string | null;
    };
    bars: ExperimentBar[];
    markers: ExperimentMarker[];
    segments: ExperimentSegment[];
}
const decimal = (x: unknown): x is string => typeof x === 'string' && /^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(x) && Number.isFinite(Number(x));
export function normalizeExperiment(value: unknown, request: ExperimentRequest): ExperimentDetail {
    const v = value as ExperimentDetail;
    const fail = (): never => {
        throw new Error('实验数据身份或数值不一致');
    };
    if (!v
                || v.schema_version !== 'newow_experiment_detail_v2'
                || v.page_parity !== true
                || v.executable !== false
                || v.formula_version !== `newow_${request.kind.replace('-', '_')}_page_v3379_v1`
                || !['READY', 'WARMUP', 'DATA_INSUFFICIENT'].includes(v.readiness?.status))
        fail();
    if (v.product !== request.product
                || v.frequency !== request.frequency
                || v.kind !== request.kind
                || previewInstant(v.as_of) === null
                || previewInstant(v.as_of) !== previewInstant(request.as_of))
        fail();
    if (!Array.isArray(v.bars)
                || !Array.isArray(v.markers)
                || !Array.isArray(v.segments))
        fail();
    const meta=v.meta, id=meta?.identity;
    if (!meta || !id || id.product!==v.product || id.frequency!==v.frequency || id.kind!==v.kind || id.strategy!==v.kind
      || v.profile_id!=='guiyi_newow_experiment_completed_physical_v1' || typeof v.input_policy_version!=='string' || !v.input_policy_version
      || id.series_kind!=='actual_dominant' || id.formula_version!==v.formula_version || id.profile_id!==v.profile_id
      || id.input_policy_version!==v.input_policy_version || id.as_of!==v.as_of || meta.as_of!==v.as_of
      || meta.input_content_sha256!==v.input_snapshot_hash || !/^[a-f0-9]{64}$/.test(meta.input_content_sha256)
      || !/^[a-f0-9]{64}$/.test(meta.result_hash) || !/^[a-f0-9]{64}$/.test(meta.data_revision_identity??'')
      || typeof meta.snapshot_token!=='string' || !meta.snapshot_token || meta.snapshot_token.length>256
      || meta.completed_only!==true || meta.executable!==false || meta.auto_order!==false
      || previewInstant(meta.read_at)===null || previewInstant(meta.read_at)!<previewInstant(meta.as_of)!
      || (request.snapshot_token!==undefined && meta.snapshot_token!==request.snapshot_token)
      || meta.last_completed_bar_end!==v.bars.at(-1)?.bar_end || meta.last_trading_day!==v.bars.at(-1)?.trading_day) fail();
    const cutoff = previewInstant(v.as_of)!;
    const segments = new Map<string, string>();
    for (const s of v.segments) {
        if (!s.segment_id
                || !s.physical_contract
                || segments.has(s.segment_id)
                || !['CURRENT', 'ROLLOVER_INTERRUPTED', 'DATA_CONFLICT'].includes(s.status))
            fail();
        segments.set(s.segment_id, s.physical_contract);
        if (s.readiness && !['READY', 'WARMUP', 'DATA_INSUFFICIENT'].includes(s.readiness.status))
            fail();
        if (s.latest_state) {
            const state = s.latest_state;
            if (typeof state.holding !== 'boolean'
                || state.holding !== (state.entry_reference_price !== null)
                || [state.entry_reference_price, state.stop_reference_price, state.locked_target, state.confirm_reference].some(x => x !== null && (!decimal(x)
                || Number(x) <= 0)))
                fail();
        }
    }
    for (const segment of v.segments)
        for (const [index, model] of [segment.ordinary, segment.theoretical].entries()) {
            if (model === null)
                continue;
            const m = model as Record<string, any>;
            if (m.page_parity !== true
                || m.executable !== false
                || m.hindsight !== (index === 1)
                || m.model_version !== (index === 0 ? 'newow_oscillation_experiment_ordinary_v3379_v1' : 'newow_base_oscillation_ideal_v3379_v1')
                || !m.summary
                || !Number.isInteger(m.summary.trade_count)
                || m.summary.trade_count < 0
                || ![m.summary.cum_return_percentage_points, m.summary.accuracy_pct, m.summary.max_drawdown_percentage_points].every(decimal)
                || !Array.isArray(m.dates)
                || !Array.isArray(m.equity)
                || m.dates.length !== m.equity.length
                || !m.equity.every(decimal)
                || !Array.isArray(m.trades)
                || !Number.isInteger(m.total_count) || m.total_count < m.trades.length)
                fail();
            let last: bigint | null = null;
            for (const date of m.dates) {
                const t = previewInstant(date);
                if (t === null
                || (last !== null && t <= last)
                || t >= cutoff)
                    fail();
                last = t;
            }
            for (const trade of m.trades) {
                if (trade.segment_id !== segment.segment_id
                || trade.physical_contract !== segment.physical_contract
                || ![trade.entry_reference_price, trade.exit_reference_price, trade.return_percentage_points].every(decimal)
                || previewInstant(trade.entry_bar_end) === null
                || previewInstant(trade.exit_bar_end) === null
                || previewInstant(trade.entry_bar_end)! > previewInstant(trade.exit_bar_end)!
                || previewInstant(trade.exit_bar_end)! >= cutoff
                || ![trade.stop_loss, trade.confirm_exit, trade.force_close].every(x => typeof x === 'boolean'))
                    fail();
            }
        }
    const bars = new Map<string, ExperimentBar>();
    let previous: bigint | null = null;
    for (const b of v.bars) {
        const t = previewInstant(b.bar_end);
        if (t === null
                || (previous !== null && t <= previous)
                || t >= cutoff
                || segments.get(b.segment_id) !== b.physical_contract
                || ![b.open, b.high, b.low, b.close].every(decimal)
                || ![b.open, b.high, b.low, b.close].every(x => Number(x) > 0)
                || Number(b.low) > Math.min(Number(b.open), Number(b.close))
                || Number(b.high) < Math.max(Number(b.open), Number(b.close))
                || Number(b.low) > Number(b.high)
                || [b.channel_high, b.channel_low].some(x => x !== null && !decimal(x)))
            fail();
        previous = t;
        bars.set(b.bar_end, b);
    }
    const ids = new Set<string>();
    for (const m of v.markers) {
        const b = bars.get(m.bar_end);
        if (!b
                || b.segment_id !== m.segment_id
                || b.physical_contract !== m.physical_contract
                || !m.marker_id
                || ids.has(m.marker_id)
                || !['BUILD', 'CLEAR'].includes(m.action)
                || !decimal(m.reference_price)
                || Number(m.reference_price) <= 0
                || !Number.isInteger(m.score)
                || m.score < 0
                || m.score > 6
                || !['⚠真突破', '⚠假突破', null].includes(m.break_label)
                || m.action === 'BUILD' && (m.stop_loss
                || m.confirm_exit)
                || typeof m.stop_loss !== 'boolean'
                || typeof m.confirm_exit !== 'boolean')
            fail();
        ids.add(m.marker_id);
    }
    return v;
}
/** A generation token also rejects responses from transports that ignore AbortSignal. */
export class ExperimentRequestGeneration {
    private generation = 0
    private controller: AbortController | null = null

    begin() {
        this.controller?.abort()
        this.controller = new AbortController()
        const id = ++this.generation
        return {
            signal: this.controller.signal,
            current: () => id === this.generation,
        }
    }

    clear() {
        this.controller?.abort()
        this.controller = null
        this.generation++
    }
}

export type ExperimentRange = '3m' | '1y' | '3y' | 'year' | 'all'

export function experimentRangeParams(asOf: string, range: ExperimentRange) {
    const instant = new Date(asOf)
    if (!Number.isFinite(instant.valueOf())) throw Error('无效快照时间')
    const day = new Date(instant.valueOf() + 8 * 3600000).toISOString().slice(0, 10)
    if (range === 'all') return { all_history: true, chart_limit: 2000 }
    const start = new Date(day + 'T00:00:00Z')
    if (range === 'year') start.setUTCMonth(0, 1)
    else if (range === '3m') start.setUTCMonth(start.getUTCMonth() - 3)
    else start.setUTCFullYear(start.getUTCFullYear() - (range === '1y' ? 1 : 3))
    return { from: start.toISOString().slice(0, 10), through: day, chart_limit: 2000 }
}

/** Presentation only: retain the chosen contract and the model's original result object. */
export function experimentVisibleSegments(detail: ExperimentDetail | null, selected: string | null) {
    const all = detail?.segments ?? []
    return all.filter(segment => segment.segment_id === (selected ?? all.at(-1)?.segment_id))
}

export function experimentMarkerLabel(marker: ExperimentMarker) {
    return marker.action === 'BUILD' ? '建仓' : marker.stop_loss ? '止损清仓' : marker.confirm_exit ? '确认清仓' : '清仓'
}

export interface ExperimentHistory {
 schema_version:'newow_experiment_history_v1';meta:ExperimentDetail['meta'];segment_id:string;physical_contract:string;
 reference_mode:'ordinary'|'theoretical';items:Record<string,unknown>[];total_count:number;next_before:string|null;
}
export function normalizeExperimentHistory(raw:unknown, panel:ExperimentDetail, request:ExperimentRequest):ExperimentHistory {
 const page=raw as ExperimentHistory, segment=panel.segments.find(s=>s.segment_id===request.segment_id), mode=request.reference_mode??'ordinary';
 const fail=()=>{throw new Error('实验历史快照或记录不一致')};
 if(!page || page.schema_version!=='newow_experiment_history_v1' || !segment || !segment[mode]
   || page.segment_id!==segment.segment_id || page.physical_contract!==segment.physical_contract || page.reference_mode!==mode
   || !page.meta || Object.entries(panel.meta).some(([key,value])=>key!=='read_at'&&key!=='identity'&&page.meta[key as keyof typeof page.meta]!==value)
   || Object.entries(panel.meta.identity).some(([key,value])=>page.meta?.identity?.[key as keyof typeof page.meta.identity]!==value)
   || !Array.isArray(page.items) || page.items.length>(request.history_limit??50) || !Number.isInteger(page.total_count)
   || page.total_count!==segment[mode]!.total_count || (page.next_before!==null && (typeof page.next_before!=='string'||!page.next_before||page.next_before.length>2048)))fail();
 normalizeExperiment({...panel,meta:page.meta,segments:panel.segments.map(s=>s.segment_id===segment!.segment_id?{...s,[mode]:{...s[mode],trades:[...page.items].reverse()}}:s)},request);
 const seen=new Set<string>();let previous:bigint|null=null;
 for(const row of page.items){const time=previewInstant(row.exit_bar_end as string)!;const key=JSON.stringify([row.entry_bar_end,row.exit_bar_end]);if(seen.has(key)||(previous!==null&&time>previous))fail();seen.add(key);previous=time}
 return page;
}
