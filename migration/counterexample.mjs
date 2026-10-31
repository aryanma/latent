// A real, local SQL execution. The fixture and the only mutation are published.
export function createCounterexample(SQL, bytes, manifest) {
  let database;
  let mutated = false;
  const original = Uint8Array.from(bytes);

  function scalar(query) {
    const result = database.exec(query);
    if (result.length !== 1 || result[0].values.length !== 1 || result[0].values[0].length !== 1) {
      throw new Error('Expected one scalar from the released query.');
    }
    const value = result[0].values[0][0];
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error('Unexpected SQL result.');
    return value;
  }

  function inspect() {
    const candidate = scalar(manifest.queries.candidate);
    const reference = scalar(manifest.queries.new_reference);
    const counts = database.exec(`SELECT COUNT(*), COUNT(DISTINCT t.CustomerID),
      SUM(CASE WHEN c.Currency = 'EUR' THEN 1 ELSE 0 END),
      COUNT(DISTINCT CASE WHEN c.Currency = 'EUR' THEN t.CustomerID END)
      FROM transactions_1k t JOIN customers c ON t.CustomerID = c.CustomerID
      WHERE t.Date = '2012-08-25'`)[0].values[0];
    return { candidate, reference, reward: Number(candidate === reference),
      transactions: counts[0], customers: counts[1], eurTransactions: counts[2], eurCustomers: counts[3], mutated };
  }

  function reset() {
    database?.close();
    database = new SQL.Database(original);
    database.run('PRAGMA foreign_keys=ON');
    mutated = false;
    const result = inspect();
    if (result.candidate !== manifest.baseline_results.candidate[0][0]
        || result.reference !== manifest.baseline_results.new_reference[0][0]) {
      throw new Error('The local baseline differs from the released witness.');
    }
    return result;
  }

  function addTransaction() {
    if (mutated) throw new Error('Reset before applying the single-row witness again.');
    database.run('BEGIN');
    try {
      database.run(manifest.mutation.statement, manifest.mutation.parameters);
      if (database.getRowsModified() !== 1) throw new Error('Expected exactly one inserted row.');
      const integrity = database.exec('PRAGMA integrity_check')[0].values;
      const foreignKeys = database.exec('PRAGMA foreign_key_check');
      if (JSON.stringify(integrity) !== '[["ok"]]' || foreignKeys.length) throw new Error('Database constraints failed.');
      const result = inspect();
      if (result.candidate !== manifest.after_insert_results.candidate[0][0]
          || result.reference !== manifest.after_insert_results.new_reference[0][0]) {
        throw new Error('The local counterexample differs from the released witness.');
      }
      database.run('COMMIT');
      mutated = true;
      return { ...result, mutated };
    } catch (error) {
      database.run('ROLLBACK');
      throw error;
    }
  }

  const baseline = reset();
  return { baseline, inspect, addTransaction, reset, close: () => database.close() };
}
