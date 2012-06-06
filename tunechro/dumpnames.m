function dumpnames

% save middlelayer ao as a table
% don't save AT information
% don't save calibration (already CSV)

ao = getao;
f = fopen('ao.csv', 'w');
fprintf(f, 'family,status,readback,setpoint,device1,device2,element,pos\n');
f2 = fopen('memberof.csv', 'w');
fprintf(f2, 'family,memberof\n');
fns = fieldnames(ao);
for n = 1:length(fns)
    fam = ao.(fns{n});
    fprintf('%s\n', fns{n});
    if size(fam.Position, 1) < size(fam.ElementList, 1)
        fprintf('%s has short position\n', fns{n});
        fam.Position = zeros(size(fam.ElementList));
    end
    for m = 1:size(fam.Monitor.ChannelNames, 1)
        dn = fam.Monitor.ChannelNames(m, :);
        dn(dn == 0) = [];
        if isfield(fam, 'Setpoint')
            dn2 = fam.Setpoint.ChannelNames(m, :);
            dn2(dn2 == 0) = [];
        else
            dn2 = '';
        end
        fprintf(f, '%s,%d,%s,%s,%d,%d,%d,%d\n', fns{n}, fam.Status(m), dn, dn2, fam.DeviceList(m, 1), fam.DeviceList(m, 2), fam.ElementList(m), fam.Position(m));
    end
    if isfield(fam, 'MemberOf')
    members = fam.MemberOf;
    for m = 1:size(members, 1)
        fprintf(f2, '%s,%s\n', fns{n}, members{m});
    end
    end
end
fclose(f);
fclose(f2);
