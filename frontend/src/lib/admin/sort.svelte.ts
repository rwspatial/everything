// Click-to-sort for the admin tables. Sorting works on the data (not the DOM), so Svelte's keyed rows stay intact:
//   const sort = new TableSort<Row>({ name: (r) => r.name, rows: (r) => r.rows });
//   {#each sort.apply(rows) as r (r.id)} … and <SortTh {sort} key="name">Name</SortTh> in the header.
// First click sorts ascending (text A→Z, numbers and dates low→high), the second descending; empty values go last.

export type SortValue = string | number | boolean | null | undefined;

export class TableSort<T> {
	key = $state<string | null>(null);
	dir = $state<'asc' | 'desc'>('asc');

	constructor(
		private readonly keys: Record<string, (row: T) => SortValue>,
		initial?: { key: string; dir?: 'asc' | 'desc' }
	) {
		if (initial) {
			this.key = initial.key;
			this.dir = initial.dir ?? 'asc';
		}
	}

	toggle(key: string): void {
		if (this.key === key) this.dir = this.dir === 'asc' ? 'desc' : 'asc';
		else {
			this.key = key;
			this.dir = 'asc';
		}
	}

	ariaSort(key: string): 'ascending' | 'descending' | 'none' {
		return this.key !== key ? 'none' : this.dir === 'asc' ? 'ascending' : 'descending';
	}

	apply(rows: T[]): T[] {
		const get = this.key ? this.keys[this.key] : undefined;
		if (!get) return rows;
		const sign = this.dir === 'asc' ? 1 : -1;
		return [...rows].sort((a, b) => {
			const x = get(a);
			const y = get(b);
			const xEmpty = x === null || x === undefined || x === '';
			const yEmpty = y === null || y === undefined || y === '';
			if (xEmpty || yEmpty) return xEmpty === yEmpty ? 0 : xEmpty ? 1 : -1; // empty last, either direction
			if (typeof x === 'number' && typeof y === 'number') return sign * (x - y);
			return sign * String(x).localeCompare(String(y), undefined, { numeric: true, sensitivity: 'base' });
		});
	}
}
