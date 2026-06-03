import { AbstractButton, AbstractButtonView } from "./abstract_button";
import type { StyleSheetLike } from "../../core/dom";
import type * as p from "../../core/properties";
import type { CallbackLike1 } from "../../core/util/callbacks";
import { Menu } from "../ui/menus";
import type { MenuView } from "../ui/menus/menu";
export declare class DropdownView extends AbstractButtonView {
    model: Dropdown;
    protected _open: boolean;
    protected menu: MenuView;
    stylesheets(): StyleSheetLike[];
    lazy_initialize(): Promise<void>;
    connect_signals(): void;
    render(): void;
    protected _build_menu(): Promise<void>;
    protected _toggle_menu(): void;
    click(): void;
    protected _item_click(i: number): void;
    to_menu(): Menu;
}
export declare namespace Dropdown {
    type Attrs = p.AttrsOf<Props>;
    type Props = AbstractButton.Props & {
        split: p.Property<boolean>;
        menu: p.Property<(string | [string, string | CallbackLike1<Dropdown, {
            index: number;
        }>] | null)[]>;
    };
}
export interface Dropdown extends Dropdown.Attrs {
}
export declare class Dropdown extends AbstractButton {
    properties: Dropdown.Props;
    __view_type__: DropdownView;
    constructor(attrs?: Partial<Dropdown.Attrs>);
    get is_split(): boolean;
}
//# sourceMappingURL=dropdown.d.ts.map