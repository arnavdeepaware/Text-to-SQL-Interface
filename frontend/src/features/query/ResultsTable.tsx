import { useMemo, useState } from "react";

import type { QueryResultColumn } from "../../types/api";

type SortDirection = "asc" | "desc";

interface SortState {
  column: string;
  direction: SortDirection;
}

interface ResultsTableProps {
  columns: QueryResultColumn[];
  rows: Record<string, unknown>[];
}

export function ResultsTable({ columns, rows }: ResultsTableProps) {
  const [sort, setSort] = useState<SortState | null>(null);
  const sortedRows = useMemo(() => sortRows(rows, sort), [rows, sort]);

  if (rows.length === 0) {
    return (
      <div className="zero-state" role="status">
        The query executed successfully and returned zero rows.
      </div>
    );
  }

  return (
    <div className="table-wrap" role="region" tabIndex={0} aria-label="Scrollable query results">
      <table>
        <caption>Query result rows</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.name} scope="col" aria-sort={ariaSort(sort, column.name)}>
                <button
                  type="button"
                  className="sort-button"
                  aria-label={sortLabel(sort, column.name)}
                  onClick={() => {
                    setSort(nextSort(sort, column.name));
                  }}
                >
                  <span>{column.name}</span>
                  <span aria-hidden="true">{sortIndicator(sort, column.name)}</span>
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row, rowIndex) => (
            <tr key={rowKey(row, rowIndex)}>
              {columns.map((column) => (
                <td key={column.name}>{formatCell(row[column.name])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function nextSort(current: SortState | null, column: string): SortState {
  if (current?.column !== column) {
    return { column, direction: "asc" };
  }

  return {
    column,
    direction: current.direction === "asc" ? "desc" : "asc"
  };
}

function sortRows(rows: Record<string, unknown>[], sort: SortState | null) {
  if (sort === null) {
    return rows;
  }

  return [...rows].sort((left, right) => {
    const comparison = compareValues(left[sort.column], right[sort.column]);
    return sort.direction === "asc" ? comparison : -comparison;
  });
}

function compareValues(left: unknown, right: unknown): number {
  if (left === right) {
    return 0;
  }

  if (left === null || left === undefined) {
    return 1;
  }

  if (right === null || right === undefined) {
    return -1;
  }

  if (typeof left === "number" && typeof right === "number") {
    return left - right;
  }

  return stringifyValue(left).localeCompare(stringifyValue(right), undefined, {
    numeric: true,
    sensitivity: "base"
  });
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) {
    return "NULL";
  }

  if (typeof value === "object") {
    return JSON.stringify(value);
  }

  return stringifyValue(value);
}

function ariaSort(sort: SortState | null, column: string): "ascending" | "descending" | "none" {
  if (sort?.column !== column) {
    return "none";
  }

  return sort.direction === "asc" ? "ascending" : "descending";
}

function sortIndicator(sort: SortState | null, column: string): string {
  if (sort?.column !== column) {
    return "Sort";
  }

  return sort.direction === "asc" ? "Asc" : "Desc";
}

function sortLabel(sort: SortState | null, column: string): string {
  if (sort?.column === column && sort.direction === "asc") {
    return `Sort ${column} descending`;
  }

  return `Sort ${column} ascending`;
}

function rowKey(row: Record<string, unknown>, rowIndex: number): string {
  return `${String(rowIndex)}:${JSON.stringify(row)}`;
}

function stringifyValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") {
    return value.toString();
  }

  if (value instanceof Date) {
    return value.toISOString();
  }

  return JSON.stringify(value);
}
