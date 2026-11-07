import { formatCell, humanize } from "../format";

type Row = Record<string, unknown>;

type Props = {
  rows: Row[];
  columns?: string[];
  maxRows?: number;
  empty?: string;
};

export function DataTable({ rows, columns, maxRows = 200, empty = "No rows." }: Props) {
  if (rows.length === 0) {
    return <div className="empty">{empty}</div>;
  }

  const headers =
    columns ??
    Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const shown = rows.slice(0, maxRows);

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header}>{humanize(header)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row, index) => (
            <tr key={index}>
              {headers.map((header) => (
                <td key={header}>{formatCell(row[header])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > maxRows ? (
        <div className="table-note">
          Showing {maxRows} of {rows.length} rows.
        </div>
      ) : null}
    </div>
  );
}
