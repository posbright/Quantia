import { UIElement, UIElementView } from "./ui_element";
import * as p from "../../core/properties";
import { HasProps } from "../../core/has_props";
import type { StyleSheetLike } from "../../core/dom";
export declare class ExaminerView extends UIElementView {
    model: Examiner;
    stylesheets(): StyleSheetLike[];
    render(): void;
}
export declare namespace Examiner {
    type Attrs = p.AttrsOf<Props>;
    type Props = UIElement.Props & {
        target: p.Property<HasProps | null>;
    };
}
export interface Examiner extends Examiner.Attrs {
}
export declare class Examiner extends UIElement {
    properties: Examiner.Props;
    __view_type__: ExaminerView;
    constructor(attrs?: Partial<Examiner.Attrs>);
}
//# sourceMappingURL=examiner.d.ts.map