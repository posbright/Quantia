import { Widget, WidgetView } from "./widget";
import type * as p from "../../core/properties";
import { Marked } from "marked";
export declare class MarkdownView extends WidgetView {
    model: Markdown;
    protected readonly _markdown: Marked<string, string>;
    readonly contents: HTMLDivElement;
    connect_signals(): void;
    protected _render_markdown(text: string): void;
    render(): void;
    get has_math_disabled(): boolean;
}
export declare namespace Markdown {
    type Attrs = p.AttrsOf<Props>;
    type Props = Widget.Props & {
        text: p.Property<string>;
        disable_math: p.Property<boolean>;
    };
}
export interface Markdown extends Markdown.Attrs {
}
export declare class Markdown extends Widget {
    properties: Markdown.Props;
    __view_type__: MarkdownView;
    constructor(attrs?: Partial<Markdown.Attrs>);
}
//# sourceMappingURL=markdown.d.ts.map