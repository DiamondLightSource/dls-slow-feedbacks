storageringinit SRI21;

SQL_HEADER = 'CREATE TABLE devices (family text, idx int, setpoint text, readback text, enabled int, hw2physics real, s real, devices text);\n';
SQL_TEMPLATE = 'INSERT INTO "devices" VALUES("%s", %d, "%s", "%s", %d, %0.10f, %0.5f, "%s");\n';

FILE = '../python/mml.sql';

f = fopen(FILE, 'w');

fprintf(f, SQL_HEADER);

cmfams = {'HCM', 'VCM'};


for i = 1:2
    cm = getfamilydata(cmfams{i});
    for j = 1:length(cm.DeviceList)
        setpoint_pv = deblank(cm.Setpoint.ChannelNames(j,:));
        readback_pv = deblank(cm.Monitor.ChannelNames(j,:));
        pv_parts = strsplit(readback_pv, ':');
        pv_prefix = pv_parts{1};
        h2p = hw2physics(cmfams{i}, 'Setpoint', 1, j);
        fprintf(f, SQL_TEMPLATE, lower(cmfams{i}), j - 1, setpoint_pv, readback_pv, 1, h2p, cm.Position(j), pv_prefix);
    end
end


bpmfams = {'BPMx'; 'BPMy'};
bpmpvs = {'SR-DI-EBPM-01:SA:X', 'SR-DI-EBPM-01:SA:Y'};

for i = 1:2
    bpm = getfamilydata(bpmfams{i});
    for j = 1:length(bpm.DeviceList)
        readback_pv = deblank(bpm.WF.ChannelNames(j,:));
        pv_parts = strsplit(readback_pv, ':');
        pv_prefix = pv_parts{1};
        fprintf(f, SQL_TEMPLATE, lower(bpmfams{i}), j - 1, bpmpvs{i}, bpmpvs{i}, 1, 0.001, bpm.Position(j), pv_prefix);
    end
end

fclose(f);
