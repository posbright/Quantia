import { HasProps } from "../../core/has_props";
import type { PlainObject } from "../../core/types";
import { Kinds, Kind } from "../../core/kinds";
import * as p from "../../core/properties";
import type { VNode } from "preact";
export declare abstract class BasePrinter {
    null(): VNode<HTMLElement>;
    token(val: string): VNode<HTMLElement>;
    boolean(val: boolean): VNode<HTMLElement>;
    number(val: number): VNode<HTMLElement>;
    string(val: string): VNode<HTMLElement>;
    symbol(val: symbol): VNode<HTMLElement>;
}
export declare class OpaqueKindPrinter extends BasePrinter {
    to_html(obj: unknown): VNode<HTMLElement>;
    ref(obj: Kinds.Ref<object>): VNode<HTMLElement>;
    struct(obj: Kinds.Struct<{
        [key: string]: unknown;
    }>): VNode<HTMLElement>;
    partial_struct(obj: Kinds.PartialStruct<{
        [key: string]: unknown;
    }>): VNode<HTMLElement>;
    func(obj: Kinds.Func<unknown[], unknown>): VNode<HTMLElement>;
    kind(obj: Kind<unknown>): VNode<HTMLElement>;
}
export declare class KindPrinter extends BasePrinter {
    private _precedence_queue;
    to_html(obj: unknown): VNode<HTMLElement>;
    protected _to_html(obj: unknown): VNode<HTMLElement>;
    precedence(kind: unknown): number;
    primitive(obj: string): VNode<HTMLElement>;
    ref(obj: Kinds.Ref<object>): VNode<HTMLElement>;
    nullable(obj: Kinds.Nullable<unknown>): VNode<HTMLElement>;
    opt(obj: Kinds.Opt<unknown>): VNode<HTMLElement>;
    list(obj: Kinds.List<unknown>): VNode<HTMLElement>;
    set(obj: Kinds.Set<unknown>): VNode<HTMLElement>;
    dict(obj: Kinds.Dict<unknown>): VNode<HTMLElement>;
    mapping(obj: Kinds.Mapping<unknown, unknown>): VNode<HTMLElement>;
    tuple(obj: Kinds.Tuple<[unknown]>): VNode<HTMLElement>;
    or(obj: Kinds.Or<[unknown]>): VNode<HTMLElement>;
    and(obj: Kinds.And<unknown, unknown>): VNode<HTMLElement>;
    enum(obj: Kinds.Enum<string | number>): VNode<HTMLElement>;
    struct(obj: Kinds.Struct<{
        [key: string]: unknown;
    }>): VNode<HTMLElement>;
    partial_struct(obj: Kinds.Struct<{
        [key: string]: unknown;
    }>): VNode<HTMLElement>;
    func(obj: Kinds.Func<unknown[], unknown>): VNode<HTMLElement>;
    regex(obj: Kinds.Regex): VNode<HTMLElement>;
    prefixed_str(obj: Kinds.PrefixedStr<string>): VNode<HTMLElement>;
}
export declare class ValuePrinter extends BasePrinter {
    readonly click?: ((obj: unknown) => void) | undefined;
    readonly max_items: number;
    readonly max_depth: number;
    protected readonly visited: WeakSet<object>;
    protected depth: number;
    constructor(click?: ((obj: unknown) => void) | undefined, max_items?: number, max_depth?: number);
    to_html(obj: unknown): VNode<HTMLElement>;
    array(obj: unknown[]): VNode<HTMLElement>;
    iterable(obj: Iterable<unknown>): VNode<HTMLElement>;
    object(obj: PlainObject): VNode<HTMLElement>;
    model(obj: HasProps): VNode<HTMLElement>;
    property(obj: p.Property): VNode<HTMLElement>;
}
//# sourceMappingURL=printers.d.ts.map